# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

"""
Extends boot info with multi-tenancy data for the client.
"""

import frappe
from frappe.multi_tenancy.tenant_manager import (
	get_current_tenant,
	get_user_tenants,
	is_multi_tenancy_enabled,
)


def extend_bootinfo(bootinfo):
	"""Add tenant information to the boot response."""
	bootinfo.multi_tenancy = {
		"enabled": is_multi_tenancy_enabled(),
	}

	if not is_multi_tenancy_enabled():
		return

	user = frappe.session.user
	current_tenant = get_current_tenant()

	bootinfo.multi_tenancy.update({
		"current_tenant": current_tenant,
		"tenants": [],
	})

	if user == "Guest":
		return

	tenants = get_user_tenants(user)
	bootinfo.multi_tenancy["tenants"] = tenants
