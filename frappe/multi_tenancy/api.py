# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

"""
Whitelisted API methods for multi-tenancy.
"""

import frappe
from frappe import _
from frappe.multi_tenancy.tenant_manager import (
	get_current_tenant,
	get_user_tenants,
	is_multi_tenancy_enabled,
	set_current_tenant,
	_apply_tenant_context,
	_user_has_tenant_access,
)


@frappe.whitelist()
def get_tenants():
	"""Return the list of tenants the current user has access to."""
	if not is_multi_tenancy_enabled():
		return {"enabled": False, "tenants": [], "current": None}

	user = frappe.session.user
	if user == "Guest":
		return {"enabled": True, "tenants": [], "current": None}

	tenants = get_user_tenants(user)
	current = get_current_tenant()

	return {
		"enabled": True,
		"tenants": tenants,
		"current": current,
	}


@frappe.whitelist()
def switch_tenant(tenant_name: str):
	"""Switch the current user to a different tenant.

	Updates the session and returns the new tenant info.
	"""
	if not is_multi_tenancy_enabled():
		frappe.throw(_("Multi-tenancy is not enabled"))

	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Guests cannot switch tenants"))

	if not _user_has_tenant_access(user, tenant_name):
		frappe.throw(_("You do not have access to tenant {0}").format(tenant_name), frappe.PermissionError)

	# Update session
	if frappe.session.data is None:
		frappe.session.data = frappe._dict()
	frappe.session.data["tenant"] = tenant_name

	# Persist to session store
	if hasattr(frappe.local, "session_obj"):
		frappe.local.session_obj.update(force=True)

	# Apply tenant context for this request
	set_current_tenant(tenant_name)
	_apply_tenant_context(tenant_name)

	# Set cookie for subsequent requests
	frappe.local.cookie_manager.set_cookie("frappe_tenant", tenant_name)

	return {
		"success": True,
		"tenant": tenant_name,
		"message": _("Switched to tenant {0}").format(tenant_name),
	}


@frappe.whitelist()
def get_tenant_info():
	"""Return info about the current tenant."""
	if not is_multi_tenancy_enabled():
		return {"enabled": False}

	current = get_current_tenant()
	if not current:
		return {"enabled": True, "current": None}

	from frappe.multi_tenancy.tenant_manager import _get_tenant_doc
	try:
		doc = _get_tenant_doc(current)
		return {
			"enabled": True,
			"current": current,
			"title": doc.get("title"),
			"isolation_mode": doc.get("isolation_mode"),
		}
	except Exception:
		return {"enabled": True, "current": current}
