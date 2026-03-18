"""SIEM Connector — pulls alerts from configured SIEM integrations."""

import json

import frappe
import requests
from frappe import _
from frappe.utils import now_datetime


def pull_all_integrations():
    """Scheduled task: pull from all enabled SIEM integrations."""
    integrations = frappe.get_all(
        "SOAR SIEM Integration",
        filters={"enabled": 1},
        fields=["name"],
    )
    for row in integrations:
        try:
            pull_from_integration(row.name)
        except Exception:
            frappe.log_error(
                title=f"SIEM Pull Error: {row.name}",
                reference_doctype="SOAR SIEM Integration",
                reference_name=row.name,
            )


def pull_from_integration(integration_name):
    """Pull alerts from a specific SIEM integration and create SOAR Alert documents.

    Returns the number of alerts created.
    """
    doc = frappe.get_doc("SOAR SIEM Integration", integration_name)

    connector = _get_connector(doc.siem_type)
    raw_alerts = connector(doc)

    sev_map = {}
    if doc.severity_mapping:
        try:
            sev_map = json.loads(doc.severity_mapping)
        except (json.JSONDecodeError, TypeError):
            pass

    count = 0
    for raw in raw_alerts:
        title = raw.get("title") or raw.get("rule", {}).get("description") or "Untitled Alert"
        source_ref = str(raw.get("id") or raw.get("_id") or "")

        if source_ref and frappe.db.exists(
            "SOAR Alert", {"source_reference": source_ref, "siem_integration": doc.name}
        ):
            continue

        raw_severity = str(raw.get("severity") or raw.get("rule", {}).get("level", ""))
        severity = sev_map.get(raw_severity, _default_severity(raw_severity))

        alert = frappe.get_doc(
            {
                "doctype": "SOAR Alert",
                "title": title[:140],
                "description": raw.get("description") or raw.get("full_log", ""),
                "severity": severity,
                "alert_type": doc.default_alert_type or raw.get("rule", {}).get("groups", [""])[0] if isinstance(raw.get("rule", {}).get("groups"), list) else (doc.default_alert_type or ""),
                "source": doc.siem_type,
                "source_reference": source_ref,
                "siem_integration": doc.name,
                "source_ip": raw.get("src_ip") or raw.get("agent", {}).get("ip", ""),
                "destination_ip": raw.get("dst_ip", ""),
                "raw_data": json.dumps(raw, indent=2, default=str),
            }
        )
        alert.insert(ignore_permissions=True)
        count += 1

    doc.db_set("last_poll_at", now_datetime(), update_modified=False)
    if count:
        frappe.db.commit()

    return count


def test_siem_connection(doc):
    """Test connectivity to the SIEM. Returns dict with status."""
    try:
        connector = _get_connector(doc.siem_type)
        connector(doc, test_only=True)
        return {"status": "ok", "message": "Connection successful"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _get_connector(siem_type):
    connectors = {
        "Wazuh": _pull_wazuh,
        "Splunk": _pull_splunk,
        "Elastic": _pull_elastic,
        "QRadar": _pull_qradar,
        "Other": _pull_generic,
    }
    return connectors.get(siem_type, _pull_generic)


# ---------- Wazuh ----------
def _pull_wazuh(doc, test_only=False):
    """Pull alerts from Wazuh API."""
    base_url = doc.api_url.rstrip("/")
    api_user = doc.api_user
    api_key = doc.get_password("api_key")
    verify = bool(doc.verify_ssl)

    # Authenticate
    auth_resp = requests.post(
        f"{base_url}/security/user/authenticate",
        auth=(api_user, api_key),
        verify=verify,
        timeout=30,
    )
    auth_resp.raise_for_status()
    token = auth_resp.json().get("data", {}).get("token", "")

    if test_only:
        return []

    headers = {"Authorization": f"Bearer {token}"}
    params = {"limit": 100, "sort": "-timestamp"}

    query_filter = _parse_query_filter(doc.query_filter)
    if query_filter:
        params.update(query_filter)

    resp = requests.get(f"{base_url}/alerts", headers=headers, params=params, verify=verify, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    return data.get("data", {}).get("affected_items", [])


# ---------- Splunk ----------
def _pull_splunk(doc, test_only=False):
    """Pull alerts from Splunk REST API."""
    base_url = doc.api_url.rstrip("/")
    token = doc.get_password("api_key")
    verify = bool(doc.verify_ssl)

    headers = {"Authorization": f"Bearer {token}"}

    if test_only:
        resp = requests.get(
            f"{base_url}/services/server/info",
            headers=headers,
            verify=verify,
            timeout=30,
        )
        resp.raise_for_status()
        return []

    search_query = "search index=_audit | head 100"
    query_filter = _parse_query_filter(doc.query_filter)
    if query_filter and "search" in query_filter:
        search_query = query_filter["search"]

    resp = requests.post(
        f"{base_url}/services/search/jobs/export",
        headers=headers,
        data={"search": search_query, "output_mode": "json"},
        verify=verify,
        timeout=120,
    )
    resp.raise_for_status()

    results = []
    for line in resp.text.strip().split("\n"):
        if line.strip():
            try:
                evt = json.loads(line)
                if "result" in evt:
                    results.append(evt["result"])
            except json.JSONDecodeError:
                continue
    return results


# ---------- Elastic ----------
def _pull_elastic(doc, test_only=False):
    """Pull alerts from Elasticsearch / Elastic SIEM."""
    base_url = doc.api_url.rstrip("/")
    api_key = doc.get_password("api_key")
    verify = bool(doc.verify_ssl)

    headers = {"Authorization": f"ApiKey {api_key}", "Content-Type": "application/json"}

    if test_only:
        resp = requests.get(f"{base_url}/_cluster/health", headers=headers, verify=verify, timeout=30)
        resp.raise_for_status()
        return []

    query = {"query": {"match_all": {}}, "size": 100, "sort": [{"@timestamp": "desc"}]}

    query_filter = _parse_query_filter(doc.query_filter)
    if query_filter:
        query["query"] = query_filter

    index = ".siem-signals-*"
    resp = requests.post(
        f"{base_url}/{index}/_search",
        headers=headers,
        json=query,
        verify=verify,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return [hit.get("_source", {}) for hit in data.get("hits", {}).get("hits", [])]


# ---------- QRadar ----------
def _pull_qradar(doc, test_only=False):
    """Pull offenses from QRadar."""
    base_url = doc.api_url.rstrip("/")
    api_key = doc.get_password("api_key")
    verify = bool(doc.verify_ssl)

    headers = {"SEC": api_key, "Accept": "application/json"}

    if test_only:
        resp = requests.get(f"{base_url}/api/system/about", headers=headers, verify=verify, timeout=30)
        resp.raise_for_status()
        return []

    params = {"filter": "status=OPEN", "Range": "items=0-99"}
    query_filter = _parse_query_filter(doc.query_filter)
    if query_filter:
        if "filter" in query_filter:
            params["filter"] = query_filter["filter"]

    resp = requests.get(
        f"{base_url}/api/siem/offenses",
        headers=headers,
        params=params,
        verify=verify,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


# ---------- Generic ----------
def _pull_generic(doc, test_only=False):
    """Generic REST pull — expects JSON array response."""
    base_url = doc.api_url.rstrip("/")
    api_key = doc.get_password("api_key")
    verify = bool(doc.verify_ssl)

    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}

    if test_only:
        requests.get(base_url, headers=headers, verify=verify, timeout=30).raise_for_status()
        return []

    resp = requests.get(base_url, headers=headers, verify=verify, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else data.get("results", data.get("data", []))


# ---------- Helpers ----------
def _parse_query_filter(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def _default_severity(raw_level):
    """Map common SIEM severity levels to SOAR severity."""
    try:
        level = int(raw_level)
        if level >= 12:
            return "Critical"
        if level >= 9:
            return "High"
        if level >= 5:
            return "Medium"
        if level >= 2:
            return "Low"
        return "Info"
    except (ValueError, TypeError):
        mapping = {
            "critical": "Critical",
            "high": "High",
            "medium": "Medium",
            "low": "Low",
            "info": "Info",
            "informational": "Info",
        }
        return mapping.get(str(raw_level).lower(), "Medium")
