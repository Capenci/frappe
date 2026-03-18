import frappe
from frappe import _
from frappe.model.document import Document


class SOARAlert(Document):
    def validate(self):
        self._validate_ips()
        self._sync_case_link()

    def _validate_ips(self):
        """Basic IP format validation."""
        import re

        ip_pattern = re.compile(
            r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$"
            r"|^[0-9a-fA-F:]+$"  # allow IPv6
        )
        for field in ("source_ip", "destination_ip"):
            value = self.get(field)
            if value and not ip_pattern.match(value):
                frappe.throw(_("{0} is not a valid IP address").format(value))

    def _sync_case_link(self):
        """When alert is assigned to a case, ensure it appears in the case's alert table."""
        if self.has_value_changed("case") and self.case:
            case_doc = frappe.get_doc("SOAR Case", self.case)
            already_linked = any(row.alert == self.name for row in case_doc.alerts)
            if not already_linked:
                case_doc.append("alerts", {"alert": self.name})
                case_doc.save(ignore_permissions=True)

    @frappe.whitelist()
    def change_status(self, new_status):
        """Explicit status change API for the form."""
        self.status = new_status
        self.save()

    @frappe.whitelist()
    def add_evidence(self, file_url, description=None):
        """Add evidence attachment."""
        self.append(
            "evidence",
            {
                "file": file_url,
                "description": description or "",
                "uploaded_by": frappe.session.user,
                "uploaded_at": frappe.utils.now_datetime(),
            },
        )
        self.save()

    @frappe.whitelist()
    def remove_evidence(self, row_name):
        """Remove an evidence row by name."""
        self.evidence = [row for row in self.evidence if row.name != row_name]
        self.save()
