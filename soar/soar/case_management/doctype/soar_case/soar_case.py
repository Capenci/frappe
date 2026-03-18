import frappe
from frappe import _
from frappe.model.document import Document


class SOARCase(Document):
    def validate(self):
        self._deduplicate_alerts()

    def on_update(self):
        self._sync_alert_case_links()

    def _deduplicate_alerts(self):
        """Remove duplicate alert entries."""
        seen = set()
        deduped = []
        for row in self.alerts:
            if row.alert not in seen:
                seen.add(row.alert)
                deduped.append(row)
        self.alerts = deduped

    def _sync_alert_case_links(self):
        """Update the case field on linked alerts."""
        for row in self.alerts:
            current_case = frappe.db.get_value("SOAR Alert", row.alert, "case")
            if current_case != self.name:
                frappe.db.set_value("SOAR Alert", row.alert, "case", self.name)

    @frappe.whitelist()
    def assign_alert(self, alert_name):
        """Assign an alert to this case."""
        already = any(row.alert == alert_name for row in self.alerts)
        if already:
            frappe.throw(_("Alert {0} is already assigned to this case").format(alert_name))
        self.append("alerts", {"alert": alert_name})
        self.save()
        frappe.db.set_value("SOAR Alert", alert_name, "case", self.name)

    @frappe.whitelist()
    def unassign_alert(self, alert_name):
        """Remove an alert from this case."""
        self.alerts = [row for row in self.alerts if row.alert != alert_name]
        self.save()
        frappe.db.set_value("SOAR Alert", alert_name, "case", None)

    @frappe.whitelist()
    def change_status(self, new_status):
        self.status = new_status
        self.save()

    @frappe.whitelist()
    def add_evidence(self, file_url, description=None):
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
        self.evidence = [row for row in self.evidence if row.name != row_name]
        self.save()
