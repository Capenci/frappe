"""SLA Service — applies SLA policies and checks for breaches/warnings."""

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime, time_diff_in_seconds


def apply_sla_on_create(doc, method=None):
    """Apply the best-matching SLA policy to a newly created document."""
    policy = _find_matching_policy(doc)
    if not policy:
        return

    now = now_datetime()
    doc.db_set("sla_policy", policy.name, update_modified=False)
    doc.db_set(
        "sla_response_deadline",
        add_to_date(now, minutes=policy.response_time_minutes),
        update_modified=False,
    )
    doc.db_set(
        "sla_resolution_deadline",
        add_to_date(now, minutes=policy.resolution_time_minutes),
        update_modified=False,
    )
    doc.db_set("sla_status", "Within SLA", update_modified=False)


def apply_sla_on_update(doc, method=None):
    """Re-evaluate SLA status when a document is saved."""
    if not doc.sla_policy:
        policy = _find_matching_policy(doc)
        if policy:
            apply_sla_on_create(doc, method)
        return

    _evaluate_sla_status(doc)


def check_sla_breaches():
    """Scheduled task: check all open documents for SLA breaches/warnings."""
    for doctype in ("SOAR Alert", "SOAR Case", "SOAR Incident"):
        _check_breaches_for_doctype(doctype)


def _check_breaches_for_doctype(doctype):
    open_docs = frappe.get_all(
        doctype,
        filters={
            "sla_policy": ("is", "set"),
            "sla_status": ("in", ("Within SLA", "Warning")),
            "status": ("not in", _closed_statuses(doctype)),
        },
        fields=["name"],
    )

    for row in open_docs:
        doc = frappe.get_doc(doctype, row.name)
        old_status = doc.sla_status
        new_status = _compute_sla_status(doc)
        if new_status != old_status:
            doc.db_set("sla_status", new_status, update_modified=False)
            if new_status == "Breached":
                _notify_sla_breach(doc)
            elif new_status == "Warning":
                _notify_sla_warning(doc)


def _evaluate_sla_status(doc):
    new_status = _compute_sla_status(doc)
    if new_status and new_status != doc.sla_status:
        doc.db_set("sla_status", new_status, update_modified=False)


def _compute_sla_status(doc):
    now = now_datetime()

    resolution_deadline = get_datetime(doc.sla_resolution_deadline) if doc.sla_resolution_deadline else None
    response_deadline = get_datetime(doc.sla_response_deadline) if doc.sla_response_deadline else None

    if resolution_deadline and now > resolution_deadline:
        return "Breached"
    if response_deadline and now > response_deadline:
        return "Breached"

    # Warning threshold
    if doc.sla_policy and resolution_deadline:
        policy = frappe.get_cached_doc("SOAR SLA Policy", doc.sla_policy)
        threshold = (policy.warning_threshold_percent or 80) / 100.0
        total_seconds = policy.resolution_time_minutes * 60
        elapsed = time_diff_in_seconds(now, get_datetime(doc.creation))
        if elapsed >= total_seconds * threshold:
            return "Warning"

    return "Within SLA"


def _find_matching_policy(doc):
    """Find the highest-priority SLA policy matching this document."""
    doctype = doc.doctype
    severity = doc.get("severity", "")

    policies = frappe.get_all(
        "SOAR SLA Policy",
        filters={"enabled": 1, "apply_to": doctype},
        fields=["name", "severity", "priority"],
        order_by="priority desc",
    )

    for p in policies:
        if p.severity == "All" or p.severity == severity:
            policy_doc = frappe.get_cached_doc("SOAR SLA Policy", p.name)
            if _conditions_match(policy_doc, doc):
                return policy_doc

    return None


def _conditions_match(policy_doc, doc):
    """Check if all conditions on the policy match the document."""
    for cond in policy_doc.conditions:
        doc_value = str(doc.get(cond.field_name, "") or "")
        cond_value = str(cond.value or "")
        op = cond.operator

        if op == "equals" and doc_value != cond_value:
            return False
        elif op == "not equals" and doc_value == cond_value:
            return False
        elif op == "contains" and cond_value not in doc_value:
            return False
        elif op == "not contains" and cond_value in doc_value:
            return False
        elif op == "is set" and not doc_value:
            return False
        elif op == "is not set" and doc_value:
            return False
        elif op == "in":
            if doc_value not in [v.strip() for v in cond_value.split(",")]:
                return False
        elif op == "not in":
            if doc_value in [v.strip() for v in cond_value.split(",")]:
                return False

    return True


def _closed_statuses(doctype):
    mapping = {
        "SOAR Alert": ("Resolved", "Closed", "False Positive"),
        "SOAR Case": ("Resolved", "Closed"),
        "SOAR Incident": ("Recovered", "Closed"),
    }
    return mapping.get(doctype, ("Closed",))


def _notify_sla_breach(doc):
    _send_sla_notification(doc, "SLA Breached", "red")


def _notify_sla_warning(doc):
    _send_sla_notification(doc, "SLA Warning", "orange")


def _send_sla_notification(doc, subject_prefix, indicator):
    assignee = doc.get("assigned_to") or doc.get("lead")
    if not assignee:
        return

    frappe.publish_realtime(
        "msgprint",
        {
            "message": f"{subject_prefix}: {doc.doctype} {doc.name} — {doc.get('title', '')}",
            "indicator": indicator,
        },
        user=assignee,
    )
