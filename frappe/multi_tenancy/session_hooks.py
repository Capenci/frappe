# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

"""
Session hooks for multi-tenancy.
Stores tenant context in the session on login/creation.
"""

import frappe
from frappe.multi_tenancy.tenant_manager import (
	_get_default_tenant,
	_get_user_default_tenant,
	get_current_tenant,
	is_multi_tenancy_enabled,
)


def on_session_creation(login_manager=None):
	"""Store the user's default tenant in the session upon login."""
	if not is_multi_tenancy_enabled():
		return

	user = frappe.session.user
	if user == "Guest":
		return

	# Determine which tenant to store in session
	current = get_current_tenant()
	if not current:
		current = _get_user_default_tenant(user) or _get_default_tenant()

	if current:
		if frappe.session.data is None:
			frappe.session.data = frappe._dict()
		frappe.session.data["tenant"] = current


def on_logout(login_manager=None):
	"""Clear tenant cookie on logout."""
	if not is_multi_tenancy_enabled():
		return

	if hasattr(frappe.local, "cookie_manager"):
		frappe.local.cookie_manager.delete_cookie("frappe_tenant")
