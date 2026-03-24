import hashlib
import hmac
import json

import frappe
from frappe import _


# ---------------------------------------------------------------------------
# New endpoint: ingest_alert  (API-key + tenant + raw_data + optional mapper)
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=True, methods=["POST"])
def ingest_alert():
    """Ingest an alert into SOAR via webhook.

    **Authentication** — one of:
      • ``X-API-Key`` request header, **or**
      • ``api_key`` field in the JSON body.

    **JSON body parameters**:
        - api_key  (str, optional if header is used)
        - tenant   (str, required) — tenant name or ID matching a SOAR Webhook Config
        - raw_data (dict, required) — the raw alert payload from the caller
        - mapper   (dict, optional) — field-mapping override; when omitted the
          default mapper stored on the SOAR Webhook Config is used.

    **Mapper format** (JSON object)::

        {
            "title":            "alert_name",
            "severity":         "priority",
            "description":      "details",
            "alert_type":       "category",
            "source_ip":        "network.src_ip",
            "destination_ip":   "network.dst_ip",
            "source_reference": "event_id",
            "severity_mapping": {
                "1": "Critical", "2": "High",
                "3": "Medium",   "4": "Low", "5": "Info"
            }
        }

    Keys are SOAR Alert field names; values are **dot-notation paths** into
    ``raw_data``.  The special key ``severity_mapping`` translates the raw
    severity value through an extra lookup table.

    **Returns** ``{"ok": true, "alert": "<alert-name>"}``
    """
    data = frappe.request.get_json(force=True, silent=True)
    if not data:
        frappe.throw(_("Invalid or empty JSON payload"), frappe.ValidationError)

    # --- resolve API key ---
    api_key = (
        frappe.request.headers.get("X-API-Key", "").strip()
        or (data.get("api_key") or "").strip()
    )
    if not api_key:
        frappe.throw(_("Missing API key. Provide X-API-Key header or api_key in the body."),
                     frappe.AuthenticationError)

    # --- resolve tenant ---
    tenant = (data.get("tenant") or "").strip()
    if not tenant:
        frappe.throw(_("'tenant' is required"), frappe.ValidationError)

    # --- look up webhook config ---
    config = _get_webhook_config(api_key, tenant)

    # --- raw_data ---
    raw_data = data.get("raw_data")
    if not raw_data or not isinstance(raw_data, dict):
        frappe.throw(_("'raw_data' must be a non-empty JSON object"), frappe.ValidationError)

    # --- mapper (request body → child table → JSON fallback) ---
    mapper = data.get("mapper")
    if mapper and not isinstance(mapper, dict):
        frappe.throw(_("'mapper' must be a JSON object"), frappe.ValidationError)

    if not mapper:
        mapper = _build_mapper_from_table(config)

    if not mapper and config.default_mapper:
        try:
            mapper = json.loads(config.default_mapper)
        except (json.JSONDecodeError, TypeError):
            mapper = None

    # --- build SOAR Alert values ---
    alert_values = _apply_mapper(raw_data, mapper, config)
    alert = frappe.get_doc(
        {
            "doctype": "SOAR Alert",
            **alert_values,
            "raw_data": json.dumps(raw_data, indent=2, default=str),
        }
    )
    alert.insert(ignore_permissions=True)
    frappe.db.commit()

    return {"ok": True, "alert": alert.name}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_webhook_config(api_key: str, tenant: str):
    """Return the matching *enabled* SOAR Webhook Config or throw."""

    configs = frappe.get_all(
        "SOAR Webhook Config",
        filters={"tenant": tenant, "enabled": 1},
        fields=["name"],
        ignore_permissions=True,
    )

    for cfg in configs:
        doc = frappe.get_doc("SOAR Webhook Config", cfg.name, ignore_permissions=True)
        print(f"Comparing API key for tenant '{tenant}': received '{api_key}', stored '{doc.get_password('api_key')}'")
        stored_key = doc.get_password("api_key") or ""
        if hmac.compare_digest(stored_key, api_key):
            return doc

    frappe.throw(
        _("No active Webhook Config found for tenant '{0}' with the provided API key").format(tenant),
        frappe.AuthenticationError,
    )


def _build_mapper_from_table(config) -> dict | None:
    """Convert the SOAR Webhook Config child-table rows into a mapper dict.

    Each row has:
        - soar_field     → key in the mapper dict
        - raw_data_field → dot-notation path (value in the mapper dict)
        - value_mapping  → optional JSON translation dict

    Returns None if the table is empty.
    """
    if not config.get("field_mappings"):
        return None

    mapper = {}
    for row in config.field_mappings:
        soar_field = (row.soar_field or "").strip()
        raw_field = (row.raw_data_field or "").strip()
        if not soar_field or not raw_field:
            continue
        mapper[soar_field] = raw_field

        # Parse optional value_mapping JSON
        if row.value_mapping and row.value_mapping.strip():
            try:
                val_map = json.loads(row.value_mapping)
                if isinstance(val_map, dict):
                    if soar_field == "severity":
                        mapper.setdefault("severity_mapping", {}).update(val_map)
                    else:
                        mapper.setdefault("select_mappings", {})[soar_field] = val_map
            except (json.JSONDecodeError, TypeError):
                pass  # ignore invalid JSON in individual rows

    return mapper if mapper else None


def _resolve_dot_path(data: dict, path: str):
    """Resolve a dot-notation path against a nested dict.

    Example: ``_resolve_dot_path({"a": {"b": "val"}}, "a.b")`` → ``"val"``
    Returns ``None`` when any segment is missing.
    """
    current = data
    for segment in path.split("."):
        if isinstance(current, dict):
            current = current.get(segment)
        else:
            return None
    return current


def _get_alert_writable_fields() -> dict:
    """Return a dict of {fieldname: fieldtype} for all writable data fields on SOAR Alert.

    Excludes layout fields (Section/Column/Tab Break), read-only fields,
    child-table fields, and internal fields managed by frappe.
    """
    meta = frappe.get_meta("SOAR Alert")
    skip_fieldtypes = {
        "Section Break", "Column Break", "Tab Break",
        "Table", "Table MultiSelect",
    }
    # Internal fields that should never be set via the mapper
    skip_fieldnames = {"name", "doctype", "owner", "creation", "modified", "modified_by", "docstatus"}

    fields = {}
    for f in meta.fields:
        if f.fieldtype in skip_fieldtypes:
            continue
        if f.fieldname in skip_fieldnames:
            continue
        fields[f.fieldname] = f.fieldtype
    return fields


def _apply_mapper(raw_data: dict, mapper: dict | None, config) -> dict:
    """Dynamically map *raw_data* fields into SOAR Alert field values.

    Reads the SOAR Alert DocType meta at runtime so any standard or custom
    field can be targeted by the mapper — no hard-coded field list.

    **Special mapper keys** (not target field names):
        - ``severity_mapping`` — dict that translates the extracted severity
          value through a lookup (e.g. ``{"1": "Critical", "2": "High"}``).
        - ``select_mappings`` — dict of ``{field: {raw_val: soar_val}}`` for
          any Select field that needs value translation.

    When no mapper is provided the function falls back to matching top-level
    keys in *raw_data* against writable SOAR Alert field names directly.
    """
    VALID_SEVERITIES = ("Info", "Low", "Medium", "High", "Critical")
    # Keys in the mapper dict that are control directives, not field mappings
    RESERVED_MAPPER_KEYS = {"severity_mapping", "select_mappings"}

    default_severity = config.default_severity or "Medium"
    default_alert_type = config.default_alert_type or ""
    source_label = config.source_label or "Webhook"

    writable = _get_alert_writable_fields()

    # ---- helpers ----
    def _coerce(value, fieldtype):
        """Best-effort coerce a value to the expected fieldtype."""
        if value is None:
            return None
        if fieldtype in ("Int", "Check"):
            try:
                return int(value)
            except (ValueError, TypeError):
                return 0
        if fieldtype in ("Float", "Currency", "Percent"):
            try:
                return float(value)
            except (ValueError, TypeError):
                return 0.0
        return str(value)

    # ================================================================
    # Path A — no mapper: auto-match top-level raw_data keys to fields
    # ================================================================
    if not mapper:
        result = {}
        for fieldname, fieldtype in writable.items():
            value = raw_data.get(fieldname)
            if value is not None:
                result[fieldname] = _coerce(value, fieldtype)

        # Ensure required defaults
        if not result.get("title"):
            result["title"] = str(raw_data.get("title") or raw_data.get("name") or "Untitled Alert")[:140]
        else:
            result["title"] = str(result["title"])[:140]

        if result.get("severity") not in VALID_SEVERITIES:
            result["severity"] = default_severity
        if not result.get("alert_type"):
            result["alert_type"] = default_alert_type
        result["source"] = source_label

        return result

    # ================================================================
    # Path B — mapper-driven extraction
    # ================================================================
    severity_mapping = mapper.get("severity_mapping") or {}
    select_mappings = mapper.get("select_mappings") or {}

    def _extract(path):
        if not path or not isinstance(path, str):
            return None
        return _resolve_dot_path(raw_data, path)

    result = {}
    for key, path in mapper.items():
        if key in RESERVED_MAPPER_KEYS:
            continue
        if key not in writable:
            continue  # ignore mapper keys that don't match a SOAR Alert field
        value = _extract(path)
        if value is not None:
            result[key] = _coerce(value, writable[key])

    # --- severity translation ---
    if "severity" in result and severity_mapping:
        raw_sev = str(result["severity"])
        result["severity"] = severity_mapping.get(raw_sev, raw_sev)

    # --- generic select-field translations ---
    for field, mapping in select_mappings.items():
        if field in result and isinstance(mapping, dict):
            raw_val = str(result[field])
            result[field] = mapping.get(raw_val, raw_val)

    # --- ensure required defaults ---
    if not result.get("title"):
        result["title"] = "Untitled Alert"
    else:
        result["title"] = str(result["title"])[:140]

    if result.get("severity") not in VALID_SEVERITIES:
        result["severity"] = default_severity
    if not result.get("alert_type"):
        result["alert_type"] = default_alert_type
    result["source"] = source_label

    return result


# ---------------------------------------------------------------------------
# Legacy endpoint (kept for backward compatibility)
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=True, methods=["POST"])
def receive():
    """Receive alerts from external webhook sources (legacy).

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
