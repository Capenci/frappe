"""Escalation Service — validates status changes and performs auto-escalation."""

import frappe
from frappe import _

# Maximum depth of chained escalation to prevent infinite loops at runtime.
_MAX_ESCALATION_DEPTH = 5


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

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
                _set_escalated_role(doc, rule.escalate_to_role)
                _notify_escalation(doc, rule, old_status, new_status)
            return


def check_auto_escalation(doc, method=None):
    """Called on_update — only trigger generic 'On Event' rules (those without a specific event_type).

    Rules with a specific event_type (e.g. 'SLA Breach') are NOT triggered here.
    They are triggered explicitly by the relevant service (e.g. sla_service calls
    trigger_event_escalation(doc, 'SLA Breach') when it detects a breach).
    """
    _run_generic_event_escalation(doc)


def trigger_event_escalation(doc, event_type=None):
    """Trigger 'On Event' escalation rules for a specific event type.

    Args:
        doc: The document that experienced the event.
        event_type: One of 'SLA Breach', 'SLA Warning', 'Priority Change',
                    'Severity Change', 'Assignment Change', or None to match
                    rules without a specific event type.
    """
    # ---- Runtime loop guard ----
    if not getattr(frappe.flags, "_escalation_chain", None):
        frappe.flags._escalation_chain = []

    chain_key = f"{doc.doctype}:{doc.name}:{event_type or '*'}"
    if chain_key in frappe.flags._escalation_chain:
        frappe.log_error(
            title="Escalation Loop Prevented",
            message=(
                f"Runtime escalation loop detected and stopped.\n"
                f"Chain: {' → '.join(frappe.flags._escalation_chain)}\n"
                f"Attempted re-entry: {chain_key}"
            ),
        )
        return

    if len(frappe.flags._escalation_chain) >= _MAX_ESCALATION_DEPTH:
        frappe.log_error(
            title="Escalation Depth Exceeded",
            message=(
                f"Escalation chain exceeded max depth ({_MAX_ESCALATION_DEPTH}).\n"
                f"Chain: {' → '.join(frappe.flags._escalation_chain)}"
            ),
        )
        return

    frappe.flags._escalation_chain.append(chain_key)

    try:
        _run_event_escalation(doc, event_type)
    finally:
        # Pop our entry so sibling triggers work correctly
        if frappe.flags._escalation_chain and frappe.flags._escalation_chain[-1] == chain_key:
            frappe.flags._escalation_chain.pop()
        # Clean up flag when the stack is empty
        if not frappe.flags._escalation_chain:
            del frappe.flags._escalation_chain


@frappe.whitelist()
def escalate_to_next_level(doctype, docname):
    """Manually escalate a ticket to the next level in its escalation flow.

    Called from the Escalate button on Alert / Case / Incident forms.
    Returns a dict with keys: escalated (bool), role (str | None), level (int | None), message (str).
    """
    doc = frappe.get_doc(doctype, docname)
    frappe.has_permission(doctype, "write", doc=doc, throw=True)

    flow_name = doc.get("escalation_flow")
    if not flow_name:
        frappe.throw(_("No escalation flow is assigned to this {0}.").format(doctype))

    flow = frappe.get_doc("SOAR Escalation Flow", flow_name)
    if not flow.enabled:
        frappe.throw(_("Escalation flow '{0}' is disabled.").format(flow.title))

    current_level = int(doc.get("escalation_level") or 0)
    levels = sorted(flow.levels, key=lambda l: l.level)

    if not levels:
        frappe.throw(_("Escalation flow '{0}' has no levels configured.").format(flow.title))

    # Find the next level
    next_level_row = None
    for lvl in levels:
        if lvl.level > current_level:
            next_level_row = lvl
            break

    if not next_level_row:
        frappe.throw(
            _("Already at the highest escalation level ({0}). Cannot escalate further.").format(
                current_level
            )
        )

    # Apply the escalation
    old_role = doc.get("escalated_to_role") or ""
    new_role = next_level_row.role
    new_level = next_level_row.level
    label = next_level_row.label or new_role

    doc.db_set("escalation_level", new_level, update_modified=True)
    doc.db_set("escalated_to_role", new_role, update_modified=False)

    # Push the update so open browsers refresh
    frappe.publish_realtime(
        "doc_update",
        {"doctype": doc.doctype, "name": doc.name},
        doctype=doc.doctype,
        docname=doc.name,
    )

    # Escalation Log
    frappe.get_doc(
        {
            "doctype": "SOAR Escalation Log",
            "escalation_rule": None,
            "reference_doctype": doc.doctype,
            "reference_name": doc.name,
            "action_taken": "Manual Escalation",
            "from_status": doc.status,
            "to_status": doc.status,
            "escalated_by": frappe.session.user,
            "escalated_to_role": new_role,
        }
    ).insert(ignore_permissions=True)

    # Notify all users in the target role
    _notify_manual_escalation(doc, new_role, old_role, current_level, new_level, label)

    frappe.msgprint(
        _("Escalated to {0} (Level {1})").format(label, new_level),
        indicator="orange",
        alert=True,
    )

    return {
        "escalated": True,
        "role": new_role,
        "level": new_level,
        "label": label,
    }


@frappe.whitelist()
def get_escalation_flow_info(doctype, docname):
    """Return the escalation flow info for the Escalate button UI.

    Returns: {flow, current_level, current_role, next_level, next_role, next_label, levels}
    """
    doc = frappe.get_doc(doctype, docname)
    frappe.has_permission(doctype, "read", doc=doc, throw=True)

    flow_name = doc.get("escalation_flow")
    if not flow_name:
        return {"flow": None}

    flow = frappe.get_doc("SOAR Escalation Flow", flow_name)
    current_level = int(doc.get("escalation_level") or 0)
    levels = sorted(flow.levels, key=lambda l: l.level)

    next_level_row = None
    for lvl in levels:
        if lvl.level > current_level:
            next_level_row = lvl
            break

    return {
        "flow": flow.title,
        "enabled": flow.enabled,
        "current_level": current_level,
        "current_role": doc.get("escalated_to_role") or "",
        "next_level": next_level_row.level if next_level_row else None,
        "next_role": next_level_row.role if next_level_row else None,
        "next_label": (next_level_row.label or next_level_row.role) if next_level_row else None,
        "levels": [
            {"level": l.level, "role": l.role, "label": l.label or l.role}
            for l in levels
        ],
    }


def _notify_manual_escalation(doc, new_role, old_role, old_level, new_level, label):
    """Send notifications for a manual escalation."""
    users = frappe.get_all(
        "Has Role",
        filters={"role": new_role, "parenttype": "User"},
        fields=["parent"],
    )

    subject = _(
        "Escalation: {0} {1} manually escalated to {2} (Level {3})"
    ).format(doc.doctype, doc.name, label, new_level)
    message = _(
        "{0} <b>{1}</b> has been manually escalated to <b>{2}</b> (Level {3}).<br>"
        "Previous role: {4} (Level {5})<br>"
        "Escalated by: {6}"
    ).format(
        doc.doctype,
        doc.name,
        label,
        new_level,
        old_role or "—",
        old_level,
        frappe.utils.get_fullname(frappe.session.user),
    )

    for u in users:
        frappe.publish_realtime(
            "msgprint",
            {"message": subject, "indicator": "orange"},
            user=u.parent,
        )
        notification = frappe.new_doc("Notification Log")
        notification.for_user = u.parent
        notification.from_user = frappe.session.user
        notification.subject = subject
        notification.email_content = message
        notification.type = "Alert"
        notification.document_type = doc.doctype
        notification.document_name = doc.name
        notification.insert(ignore_permissions=True)


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


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _run_generic_event_escalation(doc):
    """Run only generic 'On Event' rules — those with NO specific event_type.

    Called on every on_update. Rules that have a specific event_type (like
    'SLA Breach') are skipped here and only triggered by their respective service.
    """
    filters = {
        "enabled": 1,
        "apply_to": doc.doctype,
        "action": "Escalate",
        "trigger_type": "On Event",
        "event_type": ("in", ("", None)),  # only rules WITHOUT a specific event_type
    }

    rules = frappe.get_all(
        "SOAR Escalation Rule",
        filters=filters,
        fields=["name"],
        order_by="priority desc",
    )

    for r in rules:
        rule = frappe.get_cached_doc("SOAR Escalation Rule", r.name)
        if _conditions_match(rule, doc):
            _log_escalation(rule, doc, "Auto-Escalated", doc.status, doc.status)
            if rule.escalate_to_role:
                _set_escalated_role(doc, rule.escalate_to_role)
                _notify_escalation(doc, rule, doc.status, doc.status)


def _run_event_escalation(doc, event_type):
    """Run 'On Event' rules that match a SPECIFIC event_type.

    Called by services like sla_service when they detect a specific event
    (e.g. 'SLA Breach', 'SLA Warning'). Only rules whose event_type matches
    exactly will fire.
    """
    if not event_type:
        return

    filters = {
        "enabled": 1,
        "apply_to": doc.doctype,
        "action": "Escalate",
        "trigger_type": "On Event",
        "event_type": event_type,
    }

    rules = frappe.get_all(
        "SOAR Escalation Rule",
        filters=filters,
        fields=["name"],
        order_by="priority desc",
    )

    for r in rules:
        rule = frappe.get_cached_doc("SOAR Escalation Rule", r.name)
        if _conditions_match(rule, doc):
            _log_escalation(rule, doc, "Auto-Escalated", doc.status, doc.status)
            if rule.escalate_to_role:
                _set_escalated_role(doc, rule.escalate_to_role)
                _notify_escalation(doc, rule, doc.status, doc.status)


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
                _set_escalated_role(doc, rule.escalate_to_role)
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
    """Send real-time notification AND create Notification Log for all users with the target role."""
    if not rule.escalate_to_role:
        return

    users = frappe.get_all(
        "Has Role",
        filters={"role": rule.escalate_to_role, "parenttype": "User"},
        fields=["parent"],
    )

    subject = (
        f"Escalation: {doc.doctype} {doc.name} escalated to role {rule.escalate_to_role}"
    )
    message = (
        f"{doc.doctype} <b>{doc.name}</b> has been escalated to role "
        f"<b>{rule.escalate_to_role}</b>.<br>"
        f"Status: {from_status} → {to_status}<br>"
        f"Rule: {rule.name}"
    )

    for u in users:
        # Real-time toast notification
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

        # Persistent Notification Log (shows in bell icon)
        notification = frappe.new_doc("Notification Log")
        notification.for_user = u.parent
        notification.from_user = frappe.session.user
        notification.subject = subject
        notification.email_content = message
        notification.type = "Alert"
        notification.document_type = doc.doctype
        notification.document_name = doc.name
        notification.insert(ignore_permissions=True)


def _set_escalated_role(doc, role):
    """Set the escalated_to_role field on the document."""
    if doc.meta.has_field("escalated_to_role"):
        doc.db_set("escalated_to_role", role, update_modified=False)
        # Push the update so open browsers refresh
        frappe.publish_realtime(
            "doc_update",
            {"doctype": doc.doctype, "name": doc.name},
            doctype=doc.doctype,
            docname=doc.name,
        )


def _closed_statuses(doctype):
    mapping = {
        "SOAR Alert": ("Resolved", "Closed", "False Positive"),
        "SOAR Case": ("Resolved", "Closed"),
        "SOAR Incident": ("Recovered", "Closed"),
    }
    return mapping.get(doctype, ("Closed",))
