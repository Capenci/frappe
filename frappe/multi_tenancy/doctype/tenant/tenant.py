# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document


class Tenant(Document):
	# begin: auto-generated types
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		tenant_name: DF.Data
		title: DF.Data
		enabled: DF.Check
		isolation_mode: DF.Literal["schema", "database"]
		db_host: DF.Data | None
		db_port: DF.Int | None
		db_name: DF.Data | None
		db_user: DF.Data | None
		db_password: DF.Password | None
		schema_name: DF.Data | None
		description: DF.SmallText | None
		domain: DF.Data | None
		default_for_site: DF.Check
	# end: auto-generated types

	def validate(self):
		if self.isolation_mode == "database" and not self.db_name:
			frappe.throw(frappe._("Database Name is required for database isolation mode"))
		if self.isolation_mode == "schema" and not self.schema_name:
			frappe.throw(frappe._("Schema Name is required for schema isolation mode"))
		if self.default_for_site:
			self._validate_single_default()

	def _validate_single_default(self):
		"""Ensure only one tenant per site is marked as default."""
		existing = frappe.db.get_value(
			"Tenant",
			{"default_for_site": 1, "name": ("!=", self.name)},
			"name",
		)
		if existing:
			frappe.throw(
				frappe._("Tenant {0} is already the default. Unset it first.").format(existing)
			)

	def after_insert(self):
		self._sync_to_main_db()

	def on_update(self):
		frappe.cache.delete_key("tenants")
		frappe.cache.delete_key("tenant_domain_map")
		frappe.cache.delete_key("all_tenants_for_admin")
		frappe.cache.hdel("tenant_doc", self.name)
		frappe.cache.delete_key("default_tenant")
		self._sync_to_main_db()

	def on_trash(self):
		# Prevent deleting a tenant that has users
		if frappe.db.count("Tenant User", {"tenant": self.name}):
			frappe.throw(frappe._("Cannot delete tenant with assigned users. Remove users first."))
		frappe.cache.delete_key("tenants")
		frappe.cache.delete_key("tenant_domain_map")
		frappe.cache.delete_key("all_tenants_for_admin")
		frappe.cache.hdel("tenant_doc", self.name)
		frappe.cache.delete_key("default_tenant")
		self._delete_from_main_db()

	# ------------------------------------------------------------------
	# Multi-tenancy: ensure Tenant records always exist in main DB
	# ------------------------------------------------------------------

	def _is_in_tenant_context(self):
		"""Return True if we are currently operating inside a tenant schema/database."""
		from frappe.multi_tenancy.tenant_manager import (
			get_current_tenant,
			is_multi_tenancy_enabled,
		)

		if not is_multi_tenancy_enabled() or not get_current_tenant():
			return False

		has_separate_db = (
			hasattr(frappe.local, "main_db")
			and frappe.local.main_db is not frappe.local.db
		)
		has_schema = bool(getattr(frappe.local, "tenant_schema", None))
		return has_separate_db or has_schema

	def _sync_to_main_db(self):
		"""Upsert this Tenant record into the main database."""
		if not self._is_in_tenant_context():
			return

		try:
			row = frappe.db.sql(
				"SELECT * FROM `tabTenant` WHERE `name` = %s",
				self.name, as_dict=True,
			)
			if not row:
				return
			data = row[0]

			from frappe.multi_tenancy.tenant_manager import main_db_context

			has_separate_db = (
				hasattr(frappe.local, "main_db")
				and frappe.local.main_db is not frappe.local.db
			)

			if has_separate_db:
				self._write_row(frappe.local.main_db, data)
			else:
				with main_db_context() as db:
					self._write_row(db, data)
		except Exception:
			frappe.log_error(
				title="Multi-tenancy: failed to sync Tenant to main DB",
				message=frappe.get_traceback(),
			)

	def _write_row(self, db, data):
		"""Insert or update a single Tenant row in the given DB connection."""
		existing = db.sql(
			"SELECT `name` FROM `tabTenant` WHERE `name` = %s", self.name,
		)
		if existing:
			set_parts = []
			values = []
			for col, val in data.items():
				if col == "name":
					continue
				set_parts.append(f"`{col}` = %s")
				values.append(val)
			values.append(self.name)
			db.sql(
				f"UPDATE `tabTenant` SET {', '.join(set_parts)} WHERE `name` = %s",
				tuple(values),
			)
		else:
			cols = [f"`{c}`" for c in data]
			placeholders = ["%s"] * len(data)
			db.sql(
				f"INSERT INTO `tabTenant` ({', '.join(cols)}) VALUES ({', '.join(placeholders)})",
				tuple(data.values()),
			)
		db.commit()

	def _delete_from_main_db(self):
		"""Remove this Tenant record from the main database on trash."""
		if not self._is_in_tenant_context():
			return

		try:
			from frappe.multi_tenancy.tenant_manager import main_db_context

			has_separate_db = (
				hasattr(frappe.local, "main_db")
				and frappe.local.main_db is not frappe.local.db
			)

			if has_separate_db:
				frappe.local.main_db.sql(
					"DELETE FROM `tabTenant` WHERE `name` = %s", self.name,
				)
				frappe.local.main_db.commit()
			else:
				with main_db_context() as db:
					db.sql(
						"DELETE FROM `tabTenant` WHERE `name` = %s", self.name,
					)
					db.commit()
		except Exception:
			frappe.log_error(
				title="Multi-tenancy: failed to delete Tenant from main DB",
				message=frappe.get_traceback(),
			)
