import json

import frappe
from frappe import _
from frappe.model.document import Document


class SOARSLAPolicy(Document):
    def validate(self):
        if self.warning_threshold_percent and not (0 < self.warning_threshold_percent <= 100):
            frappe.throw(_("Warning Threshold must be between 1 and 100"))
        if self.response_time_minutes and self.resolution_time_minutes:
            if self.response_time_minutes > self.resolution_time_minutes:
                frappe.throw(_("Response time cannot exceed resolution time"))
