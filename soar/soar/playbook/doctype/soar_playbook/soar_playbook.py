import frappe
from frappe import _
from frappe.model.document import Document


class SOARPlaybook(Document):
    def validate(self):
        self._validate_graph()

    def _validate_graph(self):
        """Ensure the graph has exactly one Start and one End node."""
        start_nodes = [n for n in self.nodes if n.node_type == "Start"]
        end_nodes = [n for n in self.nodes if n.node_type == "End"]

        if len(start_nodes) != 1:
            frappe.throw(_("Playbook must have exactly one Start node"))
        if len(end_nodes) < 1:
            frappe.throw(_("Playbook must have at least one End node"))

        node_ids = {n.node_id for n in self.nodes}
        for edge in self.edges:
            if edge.from_node not in node_ids:
                frappe.throw(_("Edge references unknown node: {0}").format(edge.from_node))
            if edge.to_node not in node_ids:
                frappe.throw(_("Edge references unknown node: {0}").format(edge.to_node))

    @frappe.whitelist()
    def execute(self, input_data=None, trigger_doctype=None, trigger_docname=None):
        """Manually trigger playbook execution."""
        from soar.services.playbook_engine import start_execution

        return start_execution(
            playbook_name=self.name,
            trigger_type="Manual",
            input_data=input_data,
            trigger_doctype=trigger_doctype,
            trigger_docname=trigger_docname,
        )
