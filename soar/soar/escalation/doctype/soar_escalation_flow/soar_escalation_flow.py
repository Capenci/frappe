import frappe
from frappe import _
from frappe.model.document import Document


class SOAREscalationFlow(Document):
    def validate(self):
        self._validate_levels()

    def _validate_levels(self):
        """Ensure levels are numbered sequentially starting from 1."""
        if not self.levels:
            frappe.throw(_("At least one escalation level is required."))

        seen_levels = set()
        for row in self.levels:
            if row.level in seen_levels:
                frappe.throw(
                    _("Duplicate level number {0}. Each level must be unique.").format(row.level)
                )
            seen_levels.add(row.level)
            if not row.role:
                frappe.throw(_("Role is required for level {0}.").format(row.level))

        # Auto-fix: sort levels by number and re-index
        self.levels.sort(key=lambda r: r.level)
        for i, row in enumerate(self.levels, 1):
            row.idx = i
