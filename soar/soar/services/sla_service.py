"""SLA Service — applies SLA policies, tracks pause/resume, checks breaches.

Status enums
------------
sla_status:            Running | Paused | Breached | Completed
sla_response_status:   Pending | Met | Breached
sla_resolution_status: Pending | Met | Breached

Key concepts
------------
- SLA starts when the ticket (Alert/Case/Incident) is created.
- SLA **pauses** when ``status`` moves to a *pause status* (On Hold, Closed).
- SLA **resumes** when ``status`` moves to an *active status* (In Progress,
  Reopened, etc.).
- Paused duration is accumulated in ``total_paused_seconds``; deadlines are
  shifted forward on resume so the remaining SLA time is preserved.
- Once **breached**, SLA stays breached — it is never automatically reset.
- Reopening increments ``reopen_count`` and resumes SLA from where it was.
"""

import frappe
from frappe import _
from frappe.utils import (
    add_to_date,
    get_datetime,
    now_datetime,
    time_diff_in_seconds,
)

from soar.services.escalation_service import trigger_event_escalation

logger = frappe.logger("sla", allow_site=True)

# ---------------------------------------------------------------------------
# Status classification helpers
# ---------------------------------------------------------------------------

# Statuses that PAUSE the SLA clock
_PAUSE_STATUSES = {
    "SOAR Alert": ("On Hold", "Closed"),
    "SOAR Case": ("On Hold", "Closed"),
    "SOAR Incident": ("On Hold", "Closed"),
}

# Statuses that mean the ticket is "resolved" (SLA can be Completed)
_RESOLVED_STATUSES = {
    "SOAR Alert": ("Resolved",),
    "SOAR Case": ("Resolved",),
    "SOAR Incident": ("Recovered",),
}

# Statuses that count as "active" — SLA clock ticks
_ACTIVE_STATUSES = {
    "SOAR Alert": ("New", "Triaging", "In Progress", "Reopened"),
    "SOAR Case": ("New", "Open", "In Progress", "Reopened"),
    "SOAR Incident": ("New", "Open", "In Progress", "Contained", "Eradicated", "Reopened"),
}

# Statuses that mean the ticket was reopened
_REOPEN_STATUSES = ("Reopened",)

# Statuses considered as "first response" — analyst started working
_FIRST_RESPONSE_STATUSES = {
    "SOAR Alert": ("Triaging", "In Progress"),
    "SOAR Case": ("Open", "In Progress"),
    "SOAR Incident": ("Open", "In Progress"),
}


def _is_pause_status(doctype, status):
    return status in _PAUSE_STATUSES.get(doctype, ())


def _is_resolved_status(doctype, status):
    return status in _RESOLVED_STATUSES.get(doctype, ())


def _is_active_status(doctype, status):
    return status in _ACTIVE_STATUSES.get(doctype, ())


def _is_first_response_status(doctype, status):
    return status in _FIRST_RESPONSE_STATUSES.get(doctype, ())


# ---------------------------------------------------------------------------
# Doc-event hooks (called from hooks.py)
# ---------------------------------------------------------------------------

def apply_sla_on_create(doc, method=None):
    """Apply the best-matching SLA policy to a newly created document."""
    policy = _find_matching_policy(doc)
    if not policy:
        return

    now = now_datetime()
    response_due = add_to_date(now, minutes=policy.response_time_minutes)
    resolution_due = add_to_date(now, minutes=policy.resolution_time_minutes)

    doc.db_set({
        "sla_policy": policy.name,
        "sla_response_due": response_due,
        "sla_resolution_due": resolution_due,
        "sla_status": "Running",
        "sla_response_status": "Pending",
        "sla_resolution_status": "Pending",
        "total_paused_seconds": 0,
        "reopen_count": 0,
    }, update_modified=True)

    doc.reload()

    logger.info(
        f"SLA applied: {doc.doctype} {doc.name} policy={policy.name} "
        f"response_due={response_due} resolution_due={resolution_due}"
    )


def apply_sla_on_update(doc, method=None):
    """Re-evaluate SLA on every save — handles pause/resume/reopen/breach."""
    # If no policy yet, try to apply one
    if not doc.sla_policy:
        policy = _find_matching_policy(doc)
        if policy:
            apply_sla_on_create(doc, method)
        return

    if not doc.has_value_changed("status"):
        # Status didn't change — just re-evaluate current SLA numbers
        _evaluate_and_persist(doc)
        return

    now = now_datetime()
    updates = {}

    new_status = doc.status

    # ------------------------------------------------------------------
    # 1. First response detection (before anything else)
    # ------------------------------------------------------------------
    if (
        not doc.first_response_at
        and _is_first_response_status(doc.doctype, new_status)
    ):
        updates["first_response_at"] = now

    # ------------------------------------------------------------------
    # 2. Detect REOPEN
    # ------------------------------------------------------------------
    if new_status in _REOPEN_STATUSES:
        updates["reopen_count"] = (doc.reopen_count or 0) + 1
        # Clear resolved_at so resolution SLA resumes tracking
        updates["resolved_at"] = None

    # ------------------------------------------------------------------
    # 3. Detect PAUSE  (active → on_hold / closed but NOT resolved)
    # ------------------------------------------------------------------
    if _is_pause_status(doc.doctype, new_status):
        if not doc.paused_since:
            updates["paused_since"] = now

    # ------------------------------------------------------------------
    # 4. Detect RESOLVED  (any → resolved)
    # ------------------------------------------------------------------
    if _is_resolved_status(doc.doctype, new_status):
        if not doc.resolved_at:
            updates["resolved_at"] = now
        # If was paused (e.g. On Hold → Resolved directly), accumulate
        if doc.paused_since:
            paused_since = get_datetime(doc.paused_since)
            additional_pause = time_diff_in_seconds(now, paused_since)
            total = (doc.total_paused_seconds or 0) + additional_pause
            updates["total_paused_seconds"] = total
            updates["paused_since"] = None

    # ------------------------------------------------------------------
    # 5. Detect RESUME  (paused → active, not resolved)
    # ------------------------------------------------------------------
    elif _is_active_status(doc.doctype, new_status) and doc.paused_since:
        paused_since = get_datetime(doc.paused_since)
        additional_pause = time_diff_in_seconds(now, paused_since)
        total = (doc.total_paused_seconds or 0) + additional_pause

        updates["total_paused_seconds"] = total
        updates["paused_since"] = None

        # Shift deadlines forward by the pause duration
        if doc.sla_response_due:
            updates["sla_response_due"] = add_to_date(
                get_datetime(doc.sla_response_due), seconds=additional_pause
            )
        if doc.sla_resolution_due:
            updates["sla_resolution_due"] = add_to_date(
                get_datetime(doc.sla_resolution_due), seconds=additional_pause
            )

    # Persist field-level updates
    if updates:
        doc.db_set(updates, update_modified=True)
        doc.reload()

    # Now compute and persist the three SLA statuses
    _evaluate_and_persist(doc)


# ---------------------------------------------------------------------------
# Scheduled task — breach checker
# ---------------------------------------------------------------------------

def check_sla_breaches():
    """Scheduled task (runs every minute).

    Multi-tenancy aware — iterates through all enabled tenants when
    multi-tenancy is enabled (schema isolation).
    """
    from frappe.multi_tenancy.tenant_manager import (
        is_multi_tenancy_enabled,
        _apply_tenant_context,
        cleanup_tenant_context,
        main_db_context,
    )

    if is_multi_tenancy_enabled():
        with main_db_context():
            tenants = frappe.db.get_all(
                "Tenant",
                filters={"enabled": 1},
                fields=["name", "tenant_name"],
            )

        for tenant in tenants:
            try:
                _apply_tenant_context(tenant.tenant_name)
                logger.info(f"SLA check: tenant {tenant.tenant_name}")
                _check_all_doctypes()
            except Exception:
                frappe.db.rollback()
                frappe.log_error(
                    title=f"SLA Check Error — tenant {tenant.tenant_name}",
                )
            finally:
                cleanup_tenant_context()
    else:
        _check_all_doctypes()


def _check_all_doctypes():
    total_checked = 0
    total_changed = 0
    for doctype in ("SOAR Alert", "SOAR Case", "SOAR Incident"):
        checked, changed = _check_breaches_for_doctype(doctype)
        total_checked += checked
        total_changed += changed

    if total_checked:
        logger.info(
            f"SLA check: {total_checked} docs, {total_changed} changes"
        )


def _check_breaches_for_doctype(doctype):
    """Find docs with running/paused SLA and re-evaluate."""
    open_docs = frappe.get_all(
        doctype,
        filters={
            "sla_policy": ("is", "set"),
            "sla_status": ("in", ("Running", "Paused")),
        },
        fields=["name"],
    )

    checked = 0
    changed = 0

    for row in open_docs:
        checked += 1
        try:
            doc = frappe.get_doc(doctype, row.name)
            changed += _evaluate_and_persist(doc)
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()
            frappe.log_error(
                title=f"SLA Check Error — {doctype} {row.name}",
            )

    return checked, changed


# ---------------------------------------------------------------------------
# Core SLA evaluation
# ---------------------------------------------------------------------------

def _evaluate_and_persist(doc):
    """Compute all three SLA statuses and persist if changed.

    Returns 1 if any status changed, 0 otherwise.
    """
    new_sla = _compute_sla_status(doc)
    new_resp = _compute_response_status(doc)
    new_resol = _compute_resolution_status(doc)

    updates = {}
    if new_sla != doc.sla_status:
        updates["sla_status"] = new_sla
    if new_resp != doc.sla_response_status:
        updates["sla_response_status"] = new_resp
    if new_resol != doc.sla_resolution_status:
        updates["sla_resolution_status"] = new_resol

    if not updates:
        return 0

    doc.db_set(updates, update_modified=True)

    logger.info(
        f"SLA updated: {doc.doctype} {doc.name} "
        + " ".join(f"{k}={v!r}" for k, v in updates.items())
    )

    # Real-time push so the browser auto-refreshes
    frappe.publish_realtime(
        "doc_update",
        {"doctype": doc.doctype, "name": doc.name},
        doctype=doc.doctype,
        docname=doc.name,
    )

    # Escalation triggers
    if "sla_status" in updates and updates["sla_status"] == "Breached":
        _notify_sla_breach(doc)
        trigger_event_escalation(doc, "SLA Breach")
    if "sla_response_status" in updates and updates["sla_response_status"] == "Breached":
        _notify_sla_warning(doc, "Response SLA Breached")
        trigger_event_escalation(doc, "SLA Warning")

    return 1


def _compute_sla_status(doc):
    """Compute the global ``sla_status``.

    Logic priority:
    1. Sticky breach — once breached, never reverts
    2. Check if resolution deadline exceeded → Breached
    3. If status is a pause status → Paused
    4. If status is resolved and not breached → Completed
    5. Otherwise → Running
    """
    # Sticky breach — once breached, never revert
    if doc.sla_status == "Breached":
        return "Breached"

    resolution_breached = _is_resolution_breached(doc)
    if resolution_breached:
        return "Breached"

    if _is_pause_status(doc.doctype, doc.status):
        return "Paused"

    if _is_resolved_status(doc.doctype, doc.status) and not resolution_breached:
        return "Completed"

    return "Running"


def _compute_response_status(doc):
    """Compute ``sla_response_status``.

    - Sticky breach
    - If first_response_at is set and <= response_due → Met
    - If first_response_at is set and > response_due → Breached
    - If first_response_at is NULL and effective_now > response_due → Breached
    - Otherwise → Pending
    """
    if doc.sla_response_status == "Breached":
        return "Breached"

    response_due = get_datetime(doc.sla_response_due) if doc.sla_response_due else None
    if not response_due:
        return doc.sla_response_status or "Pending"

    first_response = get_datetime(doc.first_response_at) if doc.first_response_at else None

    if first_response is None:
        if _effective_now(doc) > response_due:
            return "Breached"
        return "Pending"

    if first_response <= response_due:
        return "Met"
    return "Breached"


def _compute_resolution_status(doc):
    """Compute ``sla_resolution_status``.

    - Sticky breach
    - If not resolved and effective_now > resolution_due → Breached
    - If resolved and resolved_at <= resolution_due → Met
    - If resolved and resolved_at > resolution_due → Breached
    - Otherwise → Pending
    """
    if doc.sla_resolution_status == "Breached":
        return "Breached"

    resolution_due = get_datetime(doc.sla_resolution_due) if doc.sla_resolution_due else None
    if not resolution_due:
        return doc.sla_resolution_status or "Pending"

    resolved_at = get_datetime(doc.resolved_at) if doc.resolved_at else None

    if not _is_resolved_status(doc.doctype, doc.status):
        if _effective_now(doc) > resolution_due:
            return "Breached"
        return "Pending"

    # Resolved — was it in time?
    if resolved_at and resolved_at <= resolution_due:
        return "Met"
    return "Breached"


def _is_resolution_breached(doc):
    """Quick helper: is the resolution deadline exceeded?"""
    resolution_due = get_datetime(doc.sla_resolution_due) if doc.sla_resolution_due else None
    if not resolution_due:
        return False

    resolved_at = get_datetime(doc.resolved_at) if doc.resolved_at else None
    if resolved_at:
        return resolved_at > resolution_due

    return _effective_now(doc) > resolution_due


def _effective_now(doc):
    """Return *effective* current time accounting for pause.

    If the SLA is currently paused, the effective "now" is frozen at
    ``paused_since`` (the clock stopped ticking).
    """
    if doc.paused_since:
        return get_datetime(doc.paused_since)
    return now_datetime()


# ---------------------------------------------------------------------------
# Policy matching
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Notifications (System Notification Log + realtime toast)
# ---------------------------------------------------------------------------

def _notify_sla_breach(doc):
    _send_sla_notification(doc, "SLA Breached", "red")


def _notify_sla_warning(doc, prefix="SLA Warning"):
    _send_sla_notification(doc, prefix, "orange")


def _send_sla_notification(doc, subject_prefix, indicator):
    """Create a persistent Notification Log entry + send a realtime toast.

    The Notification Log appears in the bell-icon dropdown in the navbar
    and optionally triggers an email (based on each user's notification
    settings).
    """
    recipients = _get_notification_recipients(doc)
    if not recipients:
        return

    subject = f"{subject_prefix}: {doc.doctype} {doc.name}"
    title = doc.get("title", "") or doc.name
    message = (
        f"<b>{subject_prefix}</b> for "
        f"<a href='/app/{frappe.scrub(doc.doctype)}/{doc.name}'>"
        f"{doc.doctype} {doc.name}</a>"
        f" — {title}"
    )

    # --- Persistent Notification Log ---
    from frappe.desk.doctype.notification_log.notification_log import (
        make_notification_logs,
    )

    notification_doc = {
        "type": "Alert",
        "document_type": doc.doctype,
        "document_name": doc.name,
        "subject": subject,
        "email_content": message,
        "from_user": "Administrator",
    }
    make_notification_logs(notification_doc, recipients)

    # --- Realtime toast for immediate visibility ---
    for user in recipients:
        frappe.publish_realtime(
            "msgprint",
            {
                "message": f"{subject_prefix}: {doc.doctype} {doc.name} — {title}",
                "indicator": indicator,
            },
            user=user,
        )


def _get_notification_recipients(doc):
    """Collect users who should receive SLA notifications.

    Priority: users in escalated_to_role → owner.  Returns a list of user emails.
    """
    recipients = set()

    escalated_role = doc.get("escalated_to_role")
    if escalated_role:
        role_users = frappe.get_all(
            "Has Role",
            filters={"role": escalated_role, "parenttype": "User"},
            fields=["parent"],
        )
        for u in role_users:
            recipients.add(u.parent)

    # Fallback: the document owner always gets notified
    if doc.owner and doc.owner != "Administrator":
        recipients.add(doc.owner)

    return list(recipients)
