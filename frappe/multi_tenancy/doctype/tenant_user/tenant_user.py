# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

import json

import frappe
from frappe.model.document import Document


class TenantUser(Document):
	# begin: auto-generated types
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		tenant: DF.Link
		user: DF.Link
		enabled: DF.Check
		is_default: DF.Check
		roles: DF.SmallText | None
	# end: auto-generated types

	def validate(self):
		self._validate_tenant_enabled()
		self._validate_user_enabled()
		self._validate_roles_json()
		if self.is_default:
			self._validate_single_default()

	def _validate_tenant_enabled(self):
		if not frappe.db.get_value("Tenant", self.tenant, "enabled"):
			frappe.throw(frappe._("Tenant {0} is disabled").format(self.tenant))

	def _validate_user_enabled(self):
		if not frappe.db.get_value("User", self.user, "enabled"):
			frappe.throw(frappe._("User {0} is disabled").format(self.user))

	def _validate_roles_json(self):
		if self.roles:
			try:
				roles = json.loads(self.roles)
				if not isinstance(roles, list):
					frappe.throw(frappe._("Roles must be a JSON array of role names"))
			except json.JSONDecodeError:
				frappe.throw(frappe._("Roles must be valid JSON"))

	def _validate_single_default(self):
		"""Ensure only one tenant is default per user."""
		existing = frappe.db.get_value(
			"Tenant User",
			{"user": self.user, "is_default": 1, "name": ("!=", self.name)},
			"name",
		)
		if existing:
			frappe.throw(
				frappe._("User {0} already has a default tenant. Unset it first.").format(self.user)
			)

	def after_insert(self):
		self._sync_to_main_db()

	def on_update(self):
		frappe.cache.hdel("user_tenants", self.user)
		frappe.cache.hdel("tenant_roles", f"{self.user}:{self.tenant}")
		self._sync_to_main_db()

	def on_trash(self):
		frappe.cache.hdel("user_tenants", self.user)
		frappe.cache.hdel("tenant_roles", f"{self.user}:{self.tenant}")
		self._delete_from_main_db()

	def get_tenant_roles(self):
		"""Return the list of roles for this user-tenant mapping."""
		if self.roles:
			return json.loads(self.roles)
		return []

	# ------------------------------------------------------------------
	# Multi-tenancy: ensure Tenant User records always exist in main DB
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
		"""Upsert this Tenant User record into the main database.

		The boot info and authentication helpers query Tenant User from the
		main DB, so records created/updated inside a tenant context must be
		mirrored back.
		"""
		if not self._is_in_tenant_context():
			return

		try:
			row = frappe.db.sql(
				"SELECT * FROM `tabTenant User` WHERE `name` = %s",
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
				title="Multi-tenancy: failed to sync Tenant User to main DB",
				message=frappe.get_traceback(),
			)

	def _write_row(self, db, data):
		"""Insert or update a single Tenant User row in the given DB connection."""
		existing = db.sql(
			"SELECT `name` FROM `tabTenant User` WHERE `name` = %s", self.name,
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
				f"UPDATE `tabTenant User` SET {', '.join(set_parts)} WHERE `name` = %s",
				tuple(values),
			)
		else:
			cols = [f"`{c}`" for c in data]
			placeholders = ["%s"] * len(data)
			db.sql(
				f"INSERT INTO `tabTenant User` ({', '.join(cols)}) VALUES ({', '.join(placeholders)})",
				tuple(data.values()),
			)
		db.commit()

	def _delete_from_main_db(self):
		"""Remove this Tenant User record from the main database on trash."""
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
					"DELETE FROM `tabTenant User` WHERE `name` = %s", self.name,
				)
				frappe.local.main_db.commit()
			else:
				with main_db_context() as db:
					db.sql(
						"DELETE FROM `tabTenant User` WHERE `name` = %s", self.name,
					)
					db.commit()
		except Exception:
			frappe.log_error(
				title="Multi-tenancy: failed to delete Tenant User from main DB",
				message=frappe.get_traceback(),
			)
