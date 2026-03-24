# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

"""
Tenant Manager — core logic for multi-tenant isolation.

Handles:
- Tenant resolution from request (domain, header, cookie, session)
- Database/schema switching per tenant
- Tenant-scoped role resolution
- Tenant context on frappe.local
"""

import json

import frappe
from frappe import _


def is_multi_tenancy_enabled() -> bool:
	"""Check if multi-tenancy is enabled for the current site."""
	if not hasattr(frappe.local, "conf"):
		return False
	return bool(frappe.local.conf.get("multi_tenancy_enabled"))


def get_current_tenant() -> str | None:
	"""Return the current tenant name from frappe.local, or None."""
	return getattr(frappe.local, "tenant", None)


def set_current_tenant(tenant_name: str | None) -> None:
	"""Set the current tenant on frappe.local."""
	frappe.local.tenant = tenant_name


# ---------------------------------------------------------------------------
# Tenant resolution
# ---------------------------------------------------------------------------

def resolve_tenant(request) -> str | None:
	"""Resolve the tenant for the current request.

	Resolution order:
	1. X-Frappe-Tenant header
	2. Cookie `frappe_tenant`
	3. Domain-based mapping
	4. Session stored tenant
	5. User's default tenant
	6. Site default tenant
	"""
	if not is_multi_tenancy_enabled():
		return None

	# 1. Explicit header
	tenant = request.headers.get("X-Frappe-Tenant")
	if tenant and _is_valid_tenant(tenant):
		return tenant

	# 2. Cookie
	tenant = request.cookies.get("frappe_tenant")
	if tenant and _is_valid_tenant(tenant):
		return tenant

	# 3. Domain mapping
	host = request.host.split(":")[0] if request.host else None
	if host:
		tenant = _get_tenant_for_domain(host)
		if tenant:
			return tenant

	# 4 & 5 are checked after auth in `set_tenant_after_auth`
	# 6. Site default
	return _get_default_tenant()


def set_tenant_after_auth() -> None:
	"""Called after authentication to refine tenant from session/user defaults."""
	if not is_multi_tenancy_enabled():
		return

	# Already set by header/cookie/domain
	if get_current_tenant():
		# Verify user has access
		tenant = get_current_tenant()
		user = frappe.session.user
		if user not in ("Guest", "Administrator") and not _user_has_tenant_access(user, tenant):
			# Fall back to user's default tenant
			default = _get_user_default_tenant(user)
			if default:
				set_current_tenant(default)
				_apply_tenant_context(default)
			else:
				set_current_tenant(_get_default_tenant())
				_apply_tenant_context(_get_default_tenant())
		else:
			_apply_tenant_context(tenant)
		return

	user = frappe.session.user
	if user in ("Guest", "Administrator"):
		tenant = _get_default_tenant()
	else:
		# Try session stored tenant
		session_tenant = (frappe.session.data or {}).get("tenant")
		if session_tenant and _user_has_tenant_access(user, session_tenant):
			tenant = session_tenant
		else:
			# User's default tenant
			tenant = _get_user_default_tenant(user) or _get_default_tenant()

	if tenant:
		set_current_tenant(tenant)
		_apply_tenant_context(tenant)


# ---------------------------------------------------------------------------
# Tenant context application — DB/schema switching
# ---------------------------------------------------------------------------

def _apply_tenant_context(tenant_name: str | None) -> None:
	"""Apply tenant isolation by switching DB or schema."""
	if not tenant_name:
		return

	try:
		tenant = _get_tenant_doc(tenant_name)
	except frappe.DoesNotExistError:
		return

	if not tenant.get("enabled"):
		return

	isolation_mode = tenant.get("isolation_mode")

	if isolation_mode == "database":
		_switch_to_tenant_database(tenant)
	elif isolation_mode == "schema":
		_switch_to_tenant_schema(tenant)


def _switch_to_tenant_database(tenant: dict) -> None:
	"""Switch frappe.db to the tenant's separate database."""
	from frappe.database import get_db

	db_host = tenant.get("db_host") or frappe.conf.db_host
	db_port = tenant.get("db_port") or frappe.conf.db_port
	db_name = tenant.get("db_name")
	db_user = tenant.get("db_user") or frappe.conf.db_user
	db_password = tenant.get("db_password") or frappe.conf.db_password

	if not db_name:
		return

	# Store reference to the main (shared) database for tenant management queries
	if not hasattr(frappe.local, "main_db"):
		frappe.local.main_db = frappe.local.db

	frappe.local.db = get_db(
		socket=frappe.conf.get("db_socket"),
		host=db_host,
		port=db_port,
		user=db_user,
		password=db_password,
		cur_db_name=db_name,
	)


def _switch_to_tenant_schema(tenant: dict) -> None:
	"""Switch to the tenant's schema within the same database.

	For MariaDB: uses a separate database (schemas are databases in MySQL).
	For PostgreSQL: uses SET search_path.
	"""
	schema_name = tenant.get("schema_name")
	if not schema_name:
		return

	# Store reference to main DB
	if not hasattr(frappe.local, "main_db"):
		frappe.local.main_db = frappe.local.db

	db_type = frappe.conf.get("db_type", "mariadb")

	if db_type == "postgres":
		# PostgreSQL: switch schema via search_path
		frappe.db.sql(f"SET search_path TO {frappe.db.escape(schema_name)}, public")
		frappe.local.tenant_schema = schema_name
	else:
		# MariaDB: switch to the tenant's database (schema = database in MySQL)
		frappe.db.sql(f"USE `{schema_name}`")
		frappe.local.tenant_schema = schema_name


class _MainDBContext:
	"""Context manager that temporarily switches back to the main DB schema.

	For schema isolation the same connection is reused, so ``main_db`` and
	``db`` reference the same object.  This context manager switches back
	with ``USE <main_db>`` before executing and restores afterwards.
	"""

	def __enter__(self):
		self.tenant_schema = getattr(frappe.local, "tenant_schema", None)
		if self.tenant_schema:
			frappe.db.sql(f"USE `{frappe.conf.db_name}`")
		return frappe.local.db

	def __exit__(self, *exc):
		if self.tenant_schema:
			frappe.db.sql(f"USE `{self.tenant_schema}`")


def main_db_context():
	"""Return a context manager that ensures queries run against the main DB.

	Usage::

		with main_db_context() as db:
			db.get_all("Tenant User", ...)
	"""
	return _MainDBContext()


def get_main_db():
	"""Return the main (non-tenant) database connection.

	Useful for queries on shared tables (Tenant, Tenant User, User).

	**Note:** For schema isolation the returned connection is the *same*
	object as ``frappe.db`` – use :func:`main_db_context` instead when
	you need to guarantee the main schema is active.
	"""
	return getattr(frappe.local, "main_db", frappe.local.db)


# ---------------------------------------------------------------------------
# Tenant data lookups (cached)
# ---------------------------------------------------------------------------

def _get_tenant_doc(tenant_name: str) -> dict:
	"""Get tenant document as dict, using main DB."""
	def _fetch():
		with main_db_context() as db:
			doc = db.get_value(
				"Tenant",
				tenant_name,
				[
					"name", "tenant_name", "title", "enabled", "isolation_mode",
					"db_host", "db_port", "db_name", "db_user", "db_password",
					"schema_name", "domain", "default_for_site",
				],
				as_dict=True,
			)
			if not doc:
				frappe.throw(_("Tenant {0} does not exist").format(tenant_name), frappe.DoesNotExistError)
			return doc

	return frappe.cache.hget("tenant_doc", tenant_name, _fetch)


def _is_valid_tenant(tenant_name: str) -> bool:
	"""Check if a tenant exists and is enabled."""
	try:
		doc = _get_tenant_doc(tenant_name)
		return bool(doc and doc.get("enabled"))
	except Exception:
		return False


def _get_default_tenant() -> str | None:
	"""Get the default tenant for the current site."""
	def _fetch():
		with main_db_context() as db:
			return db.get_value("Tenant", {"default_for_site": 1, "enabled": 1}, "name") or None

	return frappe.cache.get_value("default_tenant", _fetch)


def _get_tenant_for_domain(domain: str) -> str | None:
	"""Look up tenant by domain."""
	def _fetch():
		with main_db_context() as db:
			mapping = {}
			for t in db.get_all("Tenant", filters={"enabled": 1, "domain": ("is", "set")}, fields=["name", "domain"]):
				if t.domain:
					mapping[t.domain.lower()] = t.name
			return mapping

	domain_map = frappe.cache.get_value("tenant_domain_map", _fetch)
	return domain_map.get(domain.lower())


# ---------------------------------------------------------------------------
# User-tenant membership
# ---------------------------------------------------------------------------

def get_user_tenants(user: str) -> list[dict]:
	"""Return list of tenants the user has access to.

	For Administrator: returns ALL enabled tenants (admin has implicit access to every tenant).
	For other users: returns tenants from the Tenant User table.

	Returns: [{"tenant": "...", "title": "...", "is_default": 0/1, "roles": "..."}]
	"""
	if user == "Administrator":
		return _get_all_tenants_for_admin()

	def _fetch():
		with main_db_context() as db:
			return db.get_all(
				"Tenant User",
				filters={"user": user, "enabled": 1},
				fields=["tenant", "is_default", "roles"],
			)

	tenant_users = frappe.cache.hget("user_tenants", user, _fetch)

	result = []
	for tu in tenant_users:
		try:
			tenant_doc = _get_tenant_doc(tu["tenant"])
			if tenant_doc.get("enabled"):
				result.append({
					"tenant": tu["tenant"],
					"title": tenant_doc.get("title") or tu["tenant"],
					"is_default": tu.get("is_default", 0),
					"roles": tu.get("roles") or "[]",
				})
		except Exception:
			continue
	return result


def _get_all_tenants_for_admin() -> list[dict]:
	"""Return all enabled tenants for Administrator."""
	def _fetch():
		with main_db_context() as db:
			return db.get_all(
				"Tenant",
				filters={"enabled": 1},
				fields=["name", "title", "default_for_site"],
			)

	all_tenants = frappe.cache.get_value("all_tenants_for_admin", _fetch)

	result = []
	for t in all_tenants:
		result.append({
			"tenant": t["name"],
			"title": t.get("title") or t["name"],
			"is_default": t.get("default_for_site", 0),
			"roles": "[]",
		})
	return result


def _user_has_tenant_access(user: str, tenant_name: str) -> bool:
	"""Check if user has access to the given tenant."""
	if user == "Administrator":
		return True
	tenants = get_user_tenants(user)
	return any(t["tenant"] == tenant_name for t in tenants)


def _get_user_default_tenant(user: str) -> str | None:
	"""Get user's default tenant."""
	tenants = get_user_tenants(user)
	for t in tenants:
		if t.get("is_default"):
			return t["tenant"]
	# Fall back to first tenant
	return tenants[0]["tenant"] if tenants else None


# ---------------------------------------------------------------------------
# Tenant-scoped roles
# ---------------------------------------------------------------------------

def get_tenant_roles(user: str, tenant_name: str) -> list[str]:
	"""Get roles for a user within the context of a specific tenant.

	If the Tenant User record has explicit roles, those are used.
	Otherwise, the user's global roles are returned unchanged.
	"""
	if not is_multi_tenancy_enabled() or not tenant_name:
		return []

	def _fetch():
		db = get_main_db()
		roles_json = db.get_value(
			"Tenant User",
			{"user": user, "tenant": tenant_name, "enabled": 1},
			"roles",
		)
		if roles_json:
			try:
				return json.loads(roles_json)
			except (json.JSONDecodeError, TypeError):
				return []
		return []

	return frappe.cache.hget("tenant_roles", f"{user}:{tenant_name}", _fetch)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def cleanup_tenant_context() -> None:
	"""Clean up tenant-specific DB connections on request end."""
	if hasattr(frappe.local, "main_db") and frappe.local.main_db is not frappe.local.db:
		try:
			frappe.local.db.close()
		except Exception:
			pass
		frappe.local.db = frappe.local.main_db
		del frappe.local.main_db

	if hasattr(frappe.local, "tenant"):
		del frappe.local.tenant
	if hasattr(frappe.local, "tenant_schema"):
		del frappe.local.tenant_schema
