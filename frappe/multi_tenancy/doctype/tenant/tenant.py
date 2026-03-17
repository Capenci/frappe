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

	def on_update(self):
		frappe.cache.delete_key("tenants")
		frappe.cache.delete_key("tenant_domain_map")

	def on_trash(self):
		# Prevent deleting a tenant that has users
		if frappe.db.count("Tenant User", {"tenant": self.name}):
			frappe.throw(frappe._("Cannot delete tenant with assigned users. Remove users first."))
		frappe.cache.delete_key("tenants")
		frappe.cache.delete_key("tenant_domain_map")
