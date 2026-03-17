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
