import json

import frappe
from frappe import _
from frappe.model.document import Document


class SOARSIEMIntegration(Document):
    def validate(self):
        if self.severity_mapping:
            try:
                json.loads(self.severity_mapping)
            except (json.JSONDecodeError, TypeError):
                frappe.throw(_("Severity Mapping must be valid JSON"))

        if self.query_filter:
            try:
                json.loads(self.query_filter)
            except (json.JSONDecodeError, TypeError):
                frappe.throw(_("Query Filter must be valid JSON"))

    @frappe.whitelist()
    def test_connection(self):
        """Test the SIEM connection and return status."""
        from soar.services.siem_connector import test_siem_connection

        return test_siem_connection(self)

    @frappe.whitelist()
    def pull_now(self):
        """Manually trigger a pull from this SIEM integration."""
        from soar.services.siem_connector import pull_from_integration

        count = pull_from_integration(self.name)
        return {"alerts_created": count}
