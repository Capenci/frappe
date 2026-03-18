# Frappe Multi-Tenant Mode Guide

## Prerequisites

- A working Frappe bench setup with at least one site
- MariaDB or PostgreSQL database

## 1. Enable Multi-Tenancy on Your Site

```bash
bench --site mysite.localhost enable-multi-tenancy
```

This sets `"multi_tenancy_enabled": true` in your site's `site_config.json`. You can also edit it manually:

```json
{
  "multi_tenancy_enabled": true,
  "tenant_isolation": "schema",
  "default_tenant": "default"
}
```

## 2. Choose an Isolation Strategy

| Mode | Description | Best For |
|------|-------------|----------|
| **`schema`** | Each tenant gets its own DB schema (PostgreSQL: `search_path`, MariaDB: separate database via `USE`) | Lighter overhead, shared server |
| **`database`** | Each tenant gets a completely separate database connection | Stronger isolation, compliance needs |

## 3. Create Tenants

```bash
# Create tenants with your chosen isolation mode
bench --site mysite.localhost create-tenant tenant1 --isolation schema
bench --site mysite.localhost create-tenant tenant2 --isolation schema
```

Then set up the backing storage:

```bash
# For schema isolation:
bench --site mysite.localhost setup-tenant-schema tenant1
bench --site mysite.localhost setup-tenant-schema tenant2

# For database isolation:
bench --site mysite.localhost setup-tenant-db tenant1
bench --site mysite.localhost setup-tenant-db tenant2
```

## 4. Assign Users to Tenants

```bash
# Add a user to a tenant (optionally set roles and default tenant)
bench --site mysite.localhost add-tenant-user tenant1 user@example.com --default
bench --site mysite.localhost add-tenant-user tenant2 user@example.com --roles "System Manager,HR Manager"
```

## 5. Manage Tenants

```bash
# List all tenants
bench --site mysite.localhost list-tenants

# Remove a user from a tenant
bench --site mysite.localhost remove-tenant-user tenant1 user@example.com

# Remove a tenant entirely
bench --site mysite.localhost remove-tenant <name> [--force]

# Disable multi-tenancy
bench --site mysite.localhost disable-multi-tenancy
```

## 6. How Tenant Resolution Works (at runtime)

When a request comes in, the tenant is resolved in this priority order:

| Priority | Source | How |
|----------|--------|-----|
| 1 | `X-Frappe-Tenant` header | Explicit API calls |
| 2 | `frappe_tenant` cookie | Set after calling `switch_tenant` API |
| 3 | Domain mapping | Matches `Tenant.domain` field (e.g., `tenant1.example.com`) |
| 4 | Session | Stored tenant from previous login |
| 5 | User default | The tenant marked `is_default` for the user |
| 6 | Site default | The `Tenant` with `default_for_site = 1` |

## 7. Switching Tenants via API

From the client or API consumers:

```python
# Python
import frappe
frappe.call("frappe.multi_tenancy.api.switch_tenant", tenant="tenant2")
```

```javascript
// JavaScript (client-side)
frappe.call({
    method: "frappe.multi_tenancy.api.switch_tenant",
    args: { tenant: "tenant2" }
});
```

This sets a `frappe_tenant` cookie so all subsequent requests go to that tenant.

## 8. Domain-Based Tenant Routing (Optional)

You can map custom domains to tenants by setting the `domain` field on each `Tenant` doc. Then configure your reverse proxy (Nginx) to route all domains to the same Frappe site:

```nginx
server {
    server_name tenant1.example.com tenant2.example.com;
    # ... standard frappe proxy config pointing to the same site
}
```

Frappe will automatically resolve the tenant based on the incoming `Host` header.

## 9. Boot Info (Client-Side)

Once enabled, the client receives tenant info at boot:

- `frappe.boot.multi_tenancy.enabled` — whether multi-tenancy is active
- `frappe.boot.multi_tenancy.current_tenant` — active tenant name
- `frappe.boot.multi_tenancy.tenants` — list of tenants the user can access

## Key Files Reference

| File | Purpose |
|------|---------|
| `frappe/multi_tenancy/tenant_manager.py` | Core engine: resolution, DB switching, role scoping |
| `frappe/multi_tenancy/api.py` | Whitelisted APIs (`get_tenants`, `switch_tenant`, `get_tenant_info`) |
| `frappe/multi_tenancy/commands.py` | All CLI commands |
| `frappe/multi_tenancy/session_hooks.py` | Session/cookie management on login/logout |
| `frappe/multi_tenancy/boot.py` | Extends boot response with tenant data |
| `frappe/app.py` | Request lifecycle integration (Phase 1 & 2 resolution) |
