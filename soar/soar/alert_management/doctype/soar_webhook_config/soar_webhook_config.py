import json

import frappe
from frappe import _
from frappe.model.document import Document


class SOARWebhookConfig(Document):
    def validate(self):
        self._validate_mapper()

    def _validate_mapper(self):
        """Ensure the default mapper, if provided, is valid JSON."""
        if self.default_mapper:
            try:
                parsed = json.loads(self.default_mapper)
                if not isinstance(parsed, dict):
                    frappe.throw(_("Default Mapper must be a JSON object (dict)"))
            except (json.JSONDecodeError, TypeError):
                frappe.throw(_("Default Mapper must be valid JSON"))
