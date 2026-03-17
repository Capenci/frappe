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

	def on_update(self):
		frappe.cache.hdel("user_tenants", self.user)
		frappe.cache.hdel("tenant_roles", f"{self.user}:{self.tenant}")

	def on_trash(self):
		frappe.cache.hdel("user_tenants", self.user)
		frappe.cache.hdel("tenant_roles", f"{self.user}:{self.tenant}")

	def get_tenant_roles(self):
		"""Return the list of roles for this user-tenant mapping."""
		if self.roles:
			return json.loads(self.roles)
		return []
