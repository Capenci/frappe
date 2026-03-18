import frappe
from frappe import _


@frappe.whitelist()
def pull_integration(integration_name):
    """Manually pull alerts from a specific SIEM integration."""
    from soar.services.siem_connector import pull_from_integration

    count = pull_from_integration(integration_name)
    return {"alerts_created": count}


@frappe.whitelist()
def pull_all():
    """Pull alerts from all active SIEM integrations."""
    from soar.services.siem_connector import pull_all_integrations

    pull_all_integrations()
    return {"ok": True}


@frappe.whitelist()
def test_connection(integration_name):
    """Test connection to a SIEM integration."""
    from soar.services.siem_connector import test_siem_connection

    doc = frappe.get_doc("SOAR SIEM Integration", integration_name)
    return test_siem_connection(doc)
