import frappe
from frappe.model.document import Document


class SOARPlaybookExecution(Document):
    @frappe.whitelist()
    def cancel_execution(self):
        """Cancel a running execution."""
        if self.status in ("Queued", "Running"):
            self.status = "Cancelled"
            self.completed_at = frappe.utils.now_datetime()
            self.save(ignore_permissions=True)

    @frappe.whitelist()
    def get_step_status(self, node_id=None):
        """Return status of all steps or a specific step."""
        if node_id:
            for step in self.step_results:
                if step.node_id == node_id:
                    return {
                        "node_id": step.node_id,
                        "node_name": step.node_name,
                        "status": step.status,
                        "output_data": step.output_data,
                        "error": step.error,
                    }
            return None
        return [
            {
                "node_id": s.node_id,
                "node_name": s.node_name,
                "status": s.status,
            }
            for s in self.step_results
        ]
