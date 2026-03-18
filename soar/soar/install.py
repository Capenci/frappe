import frappe


def after_install():
    """Create custom roles used by the SOAR app."""
    for role_name in ("SOAR Manager", "SOAR Analyst"):
        if not frappe.db.exists("Role", role_name):
            frappe.get_doc({"doctype": "Role", "role_name": role_name, "desk_access": 1}).insert(
                ignore_permissions=True
            )
    frappe.db.commit()
