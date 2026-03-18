import frappe
from frappe import _


@frappe.whitelist()
def bulk_update_status(doctype, names, new_status):
    """Bulk update status for multiple alerts/cases/incidents.

    Args:
        doctype: 'SOAR Alert', 'SOAR Case', or 'SOAR Incident'
        names: JSON list of document names
        new_status: Target status
    """
    import json as _json

    if isinstance(names, str):
        names = _json.loads(names)

    allowed = ("SOAR Alert", "SOAR Case", "SOAR Incident")
    if doctype not in allowed:
        frappe.throw(_("Invalid DocType"))

    updated = []
    for name in names:
        doc = frappe.get_doc(doctype, name)
        doc.status = new_status
        doc.save()
        updated.append(name)

    return {"updated": updated}


@frappe.whitelist()
def get_dashboard_data():
    """Return aggregated data for the SOAR dashboard."""
    alert_stats = frappe.get_all(
        "SOAR Alert",
        fields=["status", "severity", "count(name) as count"],
        group_by="status, severity",
    )
    case_stats = frappe.get_all(
        "SOAR Case",
        fields=["status", "severity", "count(name) as count"],
        group_by="status, severity",
    )
    incident_stats = frappe.get_all(
        "SOAR Incident",
        fields=["status", "severity", "count(name) as count"],
        group_by="status, severity",
    )
    sla_stats = {
        "alerts_breached": frappe.db.count("SOAR Alert", {"sla_status": "Breached"}),
        "cases_breached": frappe.db.count("SOAR Case", {"sla_status": "Breached"}),
        "incidents_breached": frappe.db.count("SOAR Incident", {"sla_status": "Breached"}),
        "alerts_warning": frappe.db.count("SOAR Alert", {"sla_status": "Warning"}),
        "cases_warning": frappe.db.count("SOAR Case", {"sla_status": "Warning"}),
    }
    recent_alerts = frappe.get_all(
        "SOAR Alert",
        fields=["name", "title", "severity", "status", "source", "creation"],
        order_by="creation desc",
        limit_page_length=10,
    )
    return {
        "alert_stats": alert_stats,
        "case_stats": case_stats,
        "incident_stats": incident_stats,
        "sla_stats": sla_stats,
        "recent_alerts": recent_alerts,
    }
