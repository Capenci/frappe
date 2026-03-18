"""Escalation Service — validates status changes and performs auto-escalation."""

import frappe
from frappe import _


def validate_status_change(doc, method=None):
    """Called on validate — enforce escalation rules for status changes."""
    if not doc.has_value_changed("status"):
        return

    old_status = doc.get_db_value("status") if not doc.is_new() else None
    new_status = doc.status

    if not old_status:
        return

    rules = _get_matching_rules(doc.doctype, "On Status Change", old_status, new_status)

    for rule in rules:
        if not _conditions_match(rule, doc):
            continue

        if rule.action == "Deny":
            _log_escalation(rule, doc, "Denied", old_status, new_status)
            frappe.throw(
                _("Status change from {0} to {1} is denied by escalation rule: {2}").format(
                    old_status, new_status, rule.name
                )
            )

        if rule.action == "Allow":
            if rule.required_role and not _user_has_role(rule.required_role):
                frappe.throw(
                    _("Role '{0}' is required to change status from {1} to {2}").format(
                        rule.required_role, old_status, new_status
                    )
                )
            _log_escalation(rule, doc, "Allowed", old_status, new_status)
            return

        if rule.action == "Escalate":
            if not rule.auto_escalate and not _user_has_role(rule.required_role or "SOAR Manager"):
                frappe.throw(
                    _("This status change requires escalation. Role '{0}' needed.").format(
                        rule.required_role or "SOAR Manager"
                    )
                )
            _log_escalation(rule, doc, "Escalated", old_status, new_status)
            if rule.escalate_to_role:
                _notify_escalation(doc, rule, old_status, new_status)
            return


def check_auto_escalation(doc, method=None):
    """Called on_update — check if any auto-escalation rules apply."""
    rules = frappe.get_all(
        "SOAR Escalation Rule",
        filters={
            "enabled": 1,
            "apply_to": doc.doctype,
            "action": "Escalate",
            "auto_escalate": 1,
            "trigger_type": "On Event",
        },
        fields=["name"],
        order_by="priority desc",
    )

    for r in rules:
        rule = frappe.get_cached_doc("SOAR Escalation Rule", r.name)
        if _conditions_match(rule, doc):
            _log_escalation(rule, doc, "Auto-Escalated", doc.status, doc.status)
            if rule.escalate_to_role:
                _notify_escalation(doc, rule, doc.status, doc.status)


def run_scheduled_escalations():
    """Daily scheduled task — evaluate time-based escalation rules."""
    rules = frappe.get_all(
        "SOAR Escalation Rule",
        filters={
            "enabled": 1,
            "trigger_type": "Scheduled",
        },
        fields=["name"],
    )

    for r in rules:
        rule = frappe.get_cached_doc("SOAR Escalation Rule", r.name)
        _run_scheduled_rule(rule)


def _run_scheduled_rule(rule):
    """Execute a scheduled escalation rule against all matching documents."""
    doctype = rule.apply_to
    filters = {"status": ("not in", _closed_statuses(doctype))}

    docs = frappe.get_all(doctype, filters=filters, fields=["name"])
    for d in docs:
        doc = frappe.get_doc(doctype, d.name)
        if _conditions_match(rule, doc):
            if rule.action == "Escalate" and rule.escalate_to_role:
                _log_escalation(rule, doc, "Auto-Escalated", doc.status, doc.status)
                _notify_escalation(doc, rule, doc.status, doc.status)


def _get_matching_rules(doctype, trigger_type, from_status, to_status):
    filters = {
        "enabled": 1,
        "apply_to": doctype,
        "trigger_type": trigger_type,
    }

    rules = frappe.get_all(
        "SOAR Escalation Rule",
        filters=filters,
        fields=["name"],
        order_by="priority desc",
    )

    result = []
    for r in rules:
        rule = frappe.get_cached_doc("SOAR Escalation Rule", r.name)
        if rule.from_status and rule.from_status != from_status:
            continue
        if rule.to_status and rule.to_status != to_status:
            continue
        result.append(rule)

    return result


def _conditions_match(rule, doc):
    for cond in rule.conditions:
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


def _user_has_role(role_name):
    return role_name in frappe.get_roles(frappe.session.user)


def _log_escalation(rule, doc, action_taken, from_status, to_status):
    frappe.get_doc(
        {
            "doctype": "SOAR Escalation Log",
            "escalation_rule": rule.name,
            "reference_doctype": doc.doctype,
            "reference_name": doc.name,
            "action_taken": action_taken,
            "from_status": from_status,
            "to_status": to_status,
            "escalated_by": frappe.session.user,
            "escalated_to_role": rule.escalate_to_role,
        }
    ).insert(ignore_permissions=True)


def _notify_escalation(doc, rule, from_status, to_status):
    """Send real-time notification to users with the escalation target role."""
    if not rule.escalate_to_role:
        return

    users = frappe.get_all(
        "Has Role",
        filters={"role": rule.escalate_to_role, "parenttype": "User"},
        fields=["parent"],
    )

    for u in users:
        frappe.publish_realtime(
            "msgprint",
            {
                "message": (
                    f"Escalation: {doc.doctype} {doc.name} — "
                    f"status {from_status} → {to_status}. Rule: {rule.name}"
                ),
                "indicator": "orange",
            },
            user=u.parent,
        )


def _closed_statuses(doctype):
    mapping = {
        "SOAR Alert": ("Resolved", "Closed", "False Positive"),
        "SOAR Case": ("Resolved", "Closed"),
        "SOAR Incident": ("Recovered", "Closed"),
    }
    return mapping.get(doctype, ("Closed",))
