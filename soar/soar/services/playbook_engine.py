"""Playbook Engine — executes playbook graphs as background jobs."""

import json
import traceback
from collections import defaultdict, deque

import frappe
from frappe import _
from frappe.utils import now_datetime


# ──────────────────────────────────────────
# Public API
# ──────────────────────────────────────────

def start_execution(playbook_name, trigger_type="Manual", input_data=None, trigger_doctype=None, trigger_docname=None):
    """Create a Playbook Execution record and enqueue the run.

    Returns the execution document name.
    """
    playbook = frappe.get_doc("SOAR Playbook", playbook_name)

    if not playbook.is_active:
        frappe.throw(_("Playbook {0} is not active").format(playbook_name))

    # Resolve input data from trigger document
    resolved_input = _resolve_input(input_data, trigger_doctype, trigger_docname)

    execution = frappe.get_doc(
        {
            "doctype": "SOAR Playbook Execution",
            "playbook": playbook_name,
            "status": "Queued",
            "trigger_type": trigger_type,
            "trigger_doctype": trigger_doctype,
            "trigger_docname": trigger_docname,
            "input_data": json.dumps(resolved_input, indent=2, default=str) if resolved_input else "",
        }
    )
    execution.insert(ignore_permissions=True)

    # Capture tenant schema so the background worker can switch to the correct DB.
    # Multi-tenancy routes web requests to a tenant-specific database/schema,
    # but the RQ worker connects to the main database by default.
    tenant_schema = getattr(frappe.local, "tenant_schema", None)

    frappe.enqueue(
        _run_execution,
        queue="short",
        execution_name=execution.name,
        tenant_schema=tenant_schema,
        enqueue_after_commit=True,
    )

    return execution.name


def trigger_on_event(doc, method=None):
    """Doc event hook — trigger event-based playbooks."""
    playbooks = frappe.get_all(
        "SOAR Playbook",
        filters={
            "is_active": 1,
            "trigger_type": "Event",
            "trigger_doctype": doc.doctype,
        },
        fields=["name", "trigger_event", "trigger_conditions"],
    )

    event_method = method or ""
    for pb in playbooks:
        if pb.trigger_event and pb.trigger_event != event_method:
            if not (pb.trigger_event == "on_status_change" and doc.has_value_changed("status")):
                continue

        if pb.trigger_conditions:
            try:
                conditions = json.loads(pb.trigger_conditions)
                if not _match_conditions(conditions, doc):
                    continue
            except (json.JSONDecodeError, TypeError):
                pass

        start_execution(
            playbook_name=pb.name,
            trigger_type="Event",
            trigger_doctype=doc.doctype,
            trigger_docname=doc.name,
        )


def run_scheduled_playbooks():
    """Daily/cron hook — run scheduled playbooks."""
    playbooks = frappe.get_all(
        "SOAR Playbook",
        filters={"is_active": 1, "trigger_type": "Scheduled"},
        fields=["name"],
    )
    for pb in playbooks:
        start_execution(playbook_name=pb.name, trigger_type="Scheduled")


# ──────────────────────────────────────────
# Execution Engine
# ──────────────────────────────────────────

def _run_execution(execution_name, tenant_schema=None):
    """Main execution loop — processes the DAG."""
    # If multi-tenancy is active, switch to the tenant's database/schema
    # so the worker can find documents created by the web process.
    if tenant_schema:
        frappe.db.sql(f"USE `{tenant_schema}`")
        frappe.local.tenant_schema = tenant_schema

    execution = frappe.get_doc("SOAR Playbook Execution", execution_name)

    if execution.status == "Cancelled":
        return

    execution.db_set("status", "Running", update_modified=False)
    execution.db_set("started_at", now_datetime(), update_modified=False)

    playbook = frappe.get_doc("SOAR Playbook", execution.playbook)

    try:
        graph = _build_graph(playbook)
        context = {
            "input": json.loads(execution.input_data) if execution.input_data else {},
            "results": {},
        }

        # Topological execution
        _execute_graph(execution, playbook, graph, context)

        finished = now_datetime()
        execution.reload()
        execution.db_set("status", "Completed", update_modified=False)
        execution.db_set("completed_at", finished, update_modified=False)
        if execution.started_at:
            execution.db_set("duration", round((finished - execution.started_at).total_seconds(), 3), update_modified=False)

        # Store aggregated output from all completed steps
        final_output = context.get("results", {})
        if final_output:
            execution.db_set(
                "output_data",
                json.dumps(final_output, indent=2, default=str)[:100000],
                update_modified=False,
            )

    except Exception as e:
        finished = now_datetime()
        execution.reload()
        execution.db_set("status", "Failed", update_modified=False)
        execution.db_set("completed_at", finished, update_modified=False)
        if execution.started_at:
            execution.db_set("duration", round((finished - execution.started_at).total_seconds(), 3), update_modified=False)
        execution.db_set("error", traceback.format_exc(), update_modified=False)

    frappe.db.commit()


def _build_graph(playbook):
    """Build adjacency list and in-degree map from playbook nodes/edges."""
    nodes = {n.node_id: n for n in playbook.nodes}
    adj = defaultdict(list)
    in_degree = defaultdict(int)
    edge_conditions = {}

    for n in playbook.nodes:
        in_degree.setdefault(n.node_id, 0)

    for e in playbook.edges:
        adj[e.from_node].append(e.to_node)
        in_degree[e.to_node] = in_degree.get(e.to_node, 0) + 1
        if e.condition:
            edge_conditions[(e.from_node, e.to_node)] = e.condition

    return {
        "nodes": nodes,
        "adj": dict(adj),
        "in_degree": dict(in_degree),
        "edge_conditions": edge_conditions,
    }


def _execute_graph(execution, playbook, graph, context):
    """Execute the graph using Kahn's algorithm (BFS topological order)."""
    nodes = graph["nodes"]
    adj = graph["adj"]
    in_degree = dict(graph["in_degree"])
    edge_conditions = graph["edge_conditions"]

    queue = deque()
    for node_id, degree in in_degree.items():
        if degree == 0:
            queue.append(node_id)

    while queue:
        # Process all nodes at current level (supports parallel split)
        level_size = len(queue)
        for _ in range(level_size):
            node_id = queue.popleft()
            node = nodes.get(node_id)

            if not node:
                continue

            # Check if execution was cancelled
            current_status = frappe.db.get_value("SOAR Playbook Execution", execution.name, "status")
            if current_status == "Cancelled":
                return

            result = _execute_node(execution, node, context)
            context["results"][node_id] = result

            # Determine which edges to follow
            for next_id in adj.get(node_id, []):
                cond_key = (node_id, next_id)
                if cond_key in edge_conditions:
                    cond = edge_conditions[cond_key]
                    if not _evaluate_edge_condition(cond, context, result):
                        in_degree[next_id] -= 1
                        continue

                in_degree[next_id] -= 1
                if in_degree[next_id] == 0:
                    queue.append(next_id)


def _execute_node(execution, node, context):
    """Execute a single node and record the step result."""
    started = now_datetime()
    step = {
        "node_id": node.node_id,
        "node_name": node.node_name,
        "node_type": node.node_type,
        "status": "Running",
        "started_at": started,
        "input_data": json.dumps(context.get("input", {}), default=str)[:10000],
    }

    # Add step result row
    execution.reload()
    execution.append("step_results", step)
    execution.save(ignore_permissions=True)
    frappe.db.commit()

    step_row = execution.step_results[-1]

    try:
        output = _run_node_action(node, context)
        finished = now_datetime()
        duration = (finished - started).total_seconds()
        step_row.db_set("status", "Completed", update_modified=False)
        step_row.db_set("completed_at", finished, update_modified=False)
        step_row.db_set("duration", round(duration, 3), update_modified=False)
        if output is not None:
            step_row.db_set(
                "output_data",
                json.dumps(output, indent=2, default=str)[:50000],
                update_modified=False,
            )
        return output

    except Exception as e:
        finished = now_datetime()
        duration = (finished - started).total_seconds()
        step_row.db_set("status", "Failed", update_modified=False)
        step_row.db_set("completed_at", finished, update_modified=False)
        step_row.db_set("duration", round(duration, 3), update_modified=False)
        step_row.db_set("error", traceback.format_exc()[:5000], update_modified=False)
        raise


def _run_node_action(node, context):
    """Dispatch node execution based on node type and action type."""
    if node.node_type in ("Start", "End", "Parallel Join"):
        return None

    if node.node_type == "Wait":
        import time
        wait_seconds = min(node.timeout_seconds or 5, 300)
        time.sleep(wait_seconds)
        return None

    if node.node_type == "Condition":
        if node.script:
            return _safe_eval(node.script, context)
        return True

    if node.node_type == "Parallel Split":
        return None

    # Action node
    action_type = node.action_type

    if action_type == "Script":
        return _execute_script(node, context)
    elif action_type == "API Call":
        return _execute_api_call(node, context)
    elif action_type == "Send Email":
        return _execute_send_email(node, context)
    elif action_type == "Send Notification":
        return _execute_send_notification(node, context)
    elif action_type == "Update Document":
        return _execute_update_document(node, context)
    elif action_type == "Create Document":
        return _execute_create_document(node, context)
    elif action_type == "Custom":
        return _execute_custom(node, context)

    return None


def _execute_script(node, context):
    """Execute a Python script in a sandbox with essential builtins."""
    if not node.script:
        return None

    import json as _json

    local_vars = {
        "input_data": context.get("input", {}),
        "results": context.get("results", {}),
        "context": context,
        "frappe": frappe,
        "json": _json,
    }

    # Allow Python imports but provide common modules in scope already
    safe_builtins = dict(__builtins__) if isinstance(__builtins__, dict) else dict(vars(__builtins__))

    # Remove truly dangerous builtins
    for name in ("eval", "exec", "compile", "open", "breakpoint", "__import__"):
        safe_builtins.pop(name, None)

    # Controlled import that only allows approved modules
    _ALLOWED_MODULES = frozenset({
        "json", "math", "re", "datetime", "time", "hashlib", "hmac",
        "base64", "urllib", "urllib.parse", "collections", "itertools",
        "functools", "operator", "copy", "textwrap", "string",
        "frappe", "frappe.utils", "requests",
    })

    def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name not in _ALLOWED_MODULES:
            raise ImportError(f"Import of '{name}' is not allowed in playbook scripts")
        return __import__(name, globals, locals, fromlist, level)

    safe_builtins["__import__"] = _safe_import

    exec_globals = {"__builtins__": safe_builtins}
    exec(compile(node.script, f"<playbook-node-{node.node_id}>", "exec"), exec_globals, local_vars)
    return local_vars.get("result")


def _execute_api_call(node, context):
    """Make an HTTP API call based on configuration."""
    import requests as req

    config = _parse_config(node.configuration)
    url = config.get("url", "")
    method = config.get("method", "GET").upper()
    headers = config.get("headers", {})
    body = config.get("body")
    timeout = config.get("timeout", node.timeout_seconds or 30)

    if not url:
        frappe.throw(_("API Call node requires a URL in configuration"))

    resp = req.request(method, url, headers=headers, json=body, timeout=timeout)
    resp.raise_for_status()

    try:
        return resp.json()
    except Exception:
        return {"status_code": resp.status_code, "text": resp.text[:5000]}


def _execute_send_email(node, context):
    """Send email based on configuration."""
    config = _parse_config(node.configuration)
    recipients = config.get("recipients", [])
    subject = config.get("subject", "SOAR Playbook Notification")
    message = config.get("message", "")

    if isinstance(recipients, str):
        recipients = [r.strip() for r in recipients.split(",")]

    frappe.sendmail(recipients=recipients, subject=subject, message=message)
    return {"sent_to": recipients}


def _execute_send_notification(node, context):
    """Send a Frappe real-time notification."""
    config = _parse_config(node.configuration)
    users = config.get("users", [])
    message = config.get("message", "Playbook notification")

    if isinstance(users, str):
        users = [u.strip() for u in users.split(",")]

    for user in users:
        frappe.publish_realtime("msgprint", {"message": message, "indicator": "blue"}, user=user)
    return {"notified": users}


def _execute_update_document(node, context):
    """Update a Frappe document."""
    config = _parse_config(node.configuration)
    doctype = config.get("doctype")
    docname = config.get("docname")
    values = config.get("values", {})

    if not doctype or not docname:
        # Try to get from trigger context
        doctype = doctype or context.get("input", {}).get("doctype")
        docname = docname or context.get("input", {}).get("docname")

    if doctype and docname and values:
        doc = frappe.get_doc(doctype, docname)
        doc.update(values)
        doc.save(ignore_permissions=True)
        return {"updated": docname}
    return None


def _execute_create_document(node, context):
    """Create a new Frappe document."""
    config = _parse_config(node.configuration)
    doctype = config.get("doctype")
    values = config.get("values", {})

    if doctype and values:
        values["doctype"] = doctype
        doc = frappe.get_doc(values)
        doc.insert(ignore_permissions=True)
        return {"created": doc.name, "doctype": doctype}
    return None


def _execute_custom(node, context):
    """Execute a custom method path."""
    config = _parse_config(node.configuration)
    method_path = config.get("method")
    kwargs = config.get("kwargs", {})

    if method_path:
        method = frappe.get_attr(method_path)
        return method(context=context, **kwargs)
    return None


# ──────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────

def _resolve_input(input_data, trigger_doctype, trigger_docname):
    """Build input data dict, incorporating trigger document fields."""
    result = {}

    if input_data:
        if isinstance(input_data, str):
            try:
                result = json.loads(input_data)
            except (json.JSONDecodeError, TypeError):
                result = {"raw": input_data}
        elif isinstance(input_data, dict):
            result = input_data

    if trigger_doctype and trigger_docname:
        try:
            doc = frappe.get_doc(trigger_doctype, trigger_docname)
            result["doctype"] = trigger_doctype
            result["docname"] = trigger_docname
            result["doc"] = doc.as_dict()
        except Exception:
            pass

    return result


def _match_conditions(conditions, doc):
    """Check if a dict of conditions matches the document."""
    for field, expected in conditions.items():
        actual = doc.get(field)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def _safe_eval(expression, context):
    """Safely evaluate a Python expression."""
    allowed_names = {
        "input_data": context.get("input", {}),
        "results": context.get("results", {}),
        "context": context,
        "True": True,
        "False": False,
        "None": None,
    }
    return eval(expression, {"__builtins__": {}}, allowed_names)


def _evaluate_edge_condition(condition, context, node_result):
    """Evaluate an edge condition expression."""
    allowed = {
        "input_data": context.get("input", {}),
        "results": context.get("results", {}),
        "context": context,
        "result": node_result,
        "True": True,
        "False": False,
        "None": None,
    }
    try:
        return bool(eval(condition, {"__builtins__": {}}, allowed))
    except Exception:
        return True


def _parse_config(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
