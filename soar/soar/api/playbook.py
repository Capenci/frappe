import frappe
from frappe import _


@frappe.whitelist()
def execute_playbook(playbook_name, input_data=None, trigger_doctype=None, trigger_docname=None):
    """Manually trigger a playbook execution.

    Args:
        playbook_name: Name of the SOAR Playbook to execute
        input_data: Optional JSON string of input data
        trigger_doctype: Optional reference doctype
        trigger_docname: Optional reference document name
    """
    from soar.services.playbook_engine import start_execution

    execution_name = start_execution(
        playbook_name=playbook_name,
        trigger_type="Manual",
        input_data=input_data,
        trigger_doctype=trigger_doctype,
        trigger_docname=trigger_docname,
    )
    return {"execution": execution_name}


@frappe.whitelist()
def get_execution_status(execution_name):
    """Get the status and step results of a playbook execution."""
    doc = frappe.get_doc("SOAR Playbook Execution", execution_name)
    return {
        "status": doc.status,
        "started_at": str(doc.started_at) if doc.started_at else None,
        "completed_at": str(doc.completed_at) if doc.completed_at else None,
        "steps": doc.get_step_status(),
        "error": doc.error,
    }


@frappe.whitelist()
def cancel_execution(execution_name):
    """Cancel a running or queued playbook execution."""
    doc = frappe.get_doc("SOAR Playbook Execution", execution_name)
    doc.cancel_execution()
    return {"ok": True, "status": doc.status}
