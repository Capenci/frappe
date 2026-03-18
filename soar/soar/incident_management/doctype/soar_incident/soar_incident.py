import frappe
from frappe import _
from frappe.model.document import Document


class SOARIncident(Document):
    def validate(self):
        self._deduplicate_cases()

    def on_update(self):
        self._sync_case_incident_links()

    def _deduplicate_cases(self):
        seen = set()
        deduped = []
        for row in self.cases:
            if row.case not in seen:
                seen.add(row.case)
                deduped.append(row)
        self.cases = deduped

    def _sync_case_incident_links(self):
        for row in self.cases:
            current_inc = frappe.db.get_value("SOAR Case", row.case, "incident")
            if current_inc != self.name:
                frappe.db.set_value("SOAR Case", row.case, "incident", self.name)

    @frappe.whitelist()
    def add_case(self, case_name):
        already = any(row.case == case_name for row in self.cases)
        if already:
            frappe.throw(_("Case {0} is already linked to this incident").format(case_name))
        self.append("cases", {"case": case_name})
        self.save()
        frappe.db.set_value("SOAR Case", case_name, "incident", self.name)

    @frappe.whitelist()
    def remove_case(self, case_name):
        self.cases = [row for row in self.cases if row.case != case_name]
        self.save()
        frappe.db.set_value("SOAR Case", case_name, "incident", None)

    @frappe.whitelist()
    def change_status(self, new_status):
        self.status = new_status
        self.save()
