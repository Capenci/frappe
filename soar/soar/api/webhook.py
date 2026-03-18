import hashlib
import hmac
import json

import frappe
from frappe import _


@frappe.whitelist(allow_guest=True, methods=["POST"])
def receive():
    """Receive alerts from external webhook sources.

    Expects JSON body with at minimum:
        - title (str)
    Optional:
        - description, severity, alert_type, source_ip, destination_ip,
          source_reference, raw_data, webhook_secret

    Authentication: Pass `X-Webhook-Secret` header. The secret is validated
    against the site config key `soar_webhook_secret`.
    """
    _verify_webhook_secret()

    data = frappe.request.get_json(force=True, silent=True)
    if not data:
        frappe.throw(_("Invalid or empty JSON payload"), frappe.ValidationError)

    title = data.get("title")
    if not title:
        frappe.throw(_("'title' is required"), frappe.ValidationError)

    severity = data.get("severity", "Medium")
    valid_severities = ("Info", "Low", "Medium", "High", "Critical")
    if severity not in valid_severities:
        severity = "Medium"

    alert = frappe.get_doc(
        {
            "doctype": "SOAR Alert",
            "title": title,
            "description": data.get("description", ""),
            "severity": severity,
            "alert_type": data.get("alert_type", ""),
            "source": "Webhook",
            "source_reference": data.get("source_reference", ""),
            "source_ip": data.get("source_ip", ""),
            "destination_ip": data.get("destination_ip", ""),
            "raw_data": json.dumps(data.get("raw_data", data), indent=2),
        }
    )
    alert.insert(ignore_permissions=True)
    frappe.db.commit()

    return {"ok": True, "alert": alert.name}


def _verify_webhook_secret():
    """Verify the webhook secret from the request header."""
    expected = frappe.conf.get("soar_webhook_secret")
    if not expected:
        return  # no secret configured, allow all

    received = frappe.request.headers.get("X-Webhook-Secret", "")
    if not received:
        frappe.throw(_("Missing X-Webhook-Secret header"), frappe.AuthenticationError)

    if not hmac.compare_digest(str(expected), str(received)):
        frappe.throw(_("Invalid webhook secret"), frappe.AuthenticationError)
