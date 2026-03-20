import frappe
from frappe.model.document import Document


class SOARPlaybookExecution(Document):
    @frappe.whitelist()
    def cancel_execution(self):
        """Cancel a running execution."""
        if self.status in ("Queued", "Running"):
            self.status = "Cancelled"
            self.completed_at = frappe.utils.now_datetime()
            if self.started_at:
                self.duration = round(
                    (self.completed_at - self.started_at).total_seconds(), 3
                )
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
                        "node_type": step.node_type,
                        "status": step.status,
                        "duration": step.duration,
                        "output_data": step.output_data,
                        "error": step.error,
                    }
            return None
        return [
            {
                "node_id": s.node_id,
                "node_name": s.node_name,
                "node_type": s.node_type,
                "status": s.status,
                "duration": s.duration,
                "output_data": s.output_data,
                "error": s.error,
            }
            for s in self.step_results
        ]
