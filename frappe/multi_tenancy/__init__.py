# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

"""
Frappe Multi-Tenancy Module

Supports two isolation strategies:
- "schema": Each tenant gets its own database schema (same DB server)
- "database": Each tenant gets its own database (separate DB per tenant)

Configuration in site_config.json:
{
    "multi_tenancy_enabled": true,
    "tenant_isolation": "schema" | "database",
    "default_tenant": "default"
}
"""

import frappe


def sync_all_tenant_schemas():
	"""Sync all tenant schemas/databases from the main database.

	This should be called after install_app or migrate to ensure that
	all tenants receive the latest table structures (columns, indexes).

	IMPORTANT: This function only syncs schema (table structure). It does
	NOT copy data from the main DB, so tenant-specific data is preserved.
	For initial tenant setup (which copies structure + data), use the
	``_install_schema_in_tenant_*`` helpers in commands.py instead.

	The function is a no-op when multi-tenancy is not enabled.
	"""
	if not frappe.conf.get("multi_tenancy_enabled"):
		return

	from frappe.multi_tenancy.commands import (
		_sync_schema_in_tenant_db,
		_sync_schema_in_tenant_schema,
	)

	# Query tenants from the main DB (ensure we're on the main schema)
	from frappe.multi_tenancy.tenant_manager import main_db_context

	with main_db_context():
		tenants = frappe.db.get_all(
			"Tenant",
			filters={"enabled": 1},
			fields=["name", "isolation_mode", "schema_name", "db_name"],
		)

	if not tenants:
		return

	print(f"Syncing {len(tenants)} tenant(s)...")
	for tenant_info in tenants:
		tenant_name = tenant_info.name
		try:
			tenant_doc = frappe.get_doc("Tenant", tenant_name)
			if tenant_doc.isolation_mode == "schema":
				print(f"  Syncing schema for tenant '{tenant_name}'...")
				_sync_schema_in_tenant_schema(tenant_doc)
			elif tenant_doc.isolation_mode == "database":
				print(f"  Syncing database for tenant '{tenant_name}'...")
				_sync_schema_in_tenant_db(tenant_doc)
			print(f"  Tenant '{tenant_name}' synced successfully.")
		except Exception as e:
			print(f"  Warning: could not sync tenant '{tenant_name}': {e}")
