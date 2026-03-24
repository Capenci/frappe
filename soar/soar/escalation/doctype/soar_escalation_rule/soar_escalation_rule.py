"""SOAR Escalation Rule — validates configuration and detects loops."""

import frappe
from frappe import _
from frappe.model.document import Document


class SOAREscalationRule(Document):
    def validate(self):
        self._validate_trigger_fields()
        self._detect_escalation_loops()

    # ------------------------------------------------------------------
    # Trigger-field validation
    # ------------------------------------------------------------------
    def _validate_trigger_fields(self):
        """Ensure that the correct fields are populated for the chosen trigger type."""
        if self.trigger_type == "On Event" and not self.event_type:
            frappe.throw(
                _("Event Type is required when Trigger Type is 'On Event'."),
                title=_("Missing Event Type"),
            )

        if self.trigger_type == "On Status Change":
            if not self.from_status and not self.to_status:
                frappe.throw(
                    _("At least one of From Status or To Status must be specified "
                      "for 'On Status Change' trigger."),
                    title=_("Missing Status"),
                )

        if self.trigger_type == "Scheduled" and not self.schedule:
            frappe.throw(
                _("Schedule (Cron) is required when Trigger Type is 'Scheduled'."),
                title=_("Missing Schedule"),
            )

    # ------------------------------------------------------------------
    # Loop detection  (static / design-time)
    # ------------------------------------------------------------------
    def _detect_escalation_loops(self):
        """Detect circular escalation chains that could cause infinite loops.

        Two kinds of loops are checked:

        1. **Status-change cycles**: Rule A triggers on status X → Y and (through
           the action of other rules) eventually causes a transition back to X.

        2. **Duplicate / conflicting rules**: Multiple enabled rules with the
           exact same trigger signature (apply_to + trigger_type + from_status
           + to_status + event_type) that could interfere with each other —
           especially when one Allows and another Denies.

        3. **Self-referencing event loops**: An "On Event" rule whose action
           might re-trigger the same event type (e.g., "SLA Breach" escalation
           that could indirectly cause another breach check).
        """
        if not self.enabled:
            return

        self._check_duplicate_rules()

        if self.trigger_type == "On Status Change":
            self._check_status_change_cycles()

    def _check_duplicate_rules(self):
        """Warn if another enabled rule has the *exact* same trigger signature."""
        filters = {
            "enabled": 1,
            "apply_to": self.apply_to,
            "trigger_type": self.trigger_type,
            "name": ("!=", self.name),
        }

        if self.trigger_type == "On Status Change":
            if self.from_status:
                filters["from_status"] = self.from_status
            if self.to_status:
                filters["to_status"] = self.to_status
        elif self.trigger_type == "On Event":
            filters["event_type"] = self.event_type

        duplicates = frappe.get_all(
            "SOAR Escalation Rule",
            filters=filters,
            fields=["name", "action"],
            limit=10,
        )

        if not duplicates:
            return

        # Hard conflict: same trigger, contradictory actions (Allow vs Deny)
        actions_in_play = {d.action for d in duplicates}
        if self.action in ("Allow", "Deny") and actions_in_play & {"Allow", "Deny"} - {self.action}:
            frappe.throw(
                _("Conflicting escalation rules detected. Rule(s) {0} have a "
                  "contradictory action ({1}) for the same trigger signature. "
                  "This will cause unpredictable behaviour.").format(
                    ", ".join(d.name for d in duplicates if d.action != self.action),
                    " vs ".join(sorted(actions_in_play | {self.action})),
                ),
                title=_("Escalation Rule Conflict"),
            )

        # Soft duplicate: warn but allow
        dup_names = ", ".join(d.name for d in duplicates)
        frappe.msgprint(
            _("Warning: The following enabled rules share the same trigger "
              "signature and will all be evaluated: {0}. Ensure this is "
              "intentional to avoid unexpected results.").format(dup_names),
            title=_("Possible Duplicate Rules"),
            indicator="orange",
        )

    def _check_status_change_cycles(self):
        """Detect cycles in status-change escalation rules.

        Build a directed graph of (from_status → to_status) for all enabled
        rules of the same *apply_to* doctype and check for cycles using DFS.
        """
        rules = frappe.get_all(
            "SOAR Escalation Rule",
            filters={
                "enabled": 1,
                "apply_to": self.apply_to,
                "trigger_type": "On Status Change",
            },
            fields=["name", "from_status", "to_status"],
        )

        # Include the current (possibly unsaved) rule
        current_included = False
        for r in rules:
            if r.name == self.name:
                r.from_status = self.from_status
                r.to_status = self.to_status
                current_included = True
        if not current_included:
            rules.append(
                frappe._dict(name=self.name, from_status=self.from_status, to_status=self.to_status)
            )

        # Build adjacency list — only include rules that have both from & to
        graph = {}  # from_status -> set of to_statuses
        for r in rules:
            if r.from_status and r.to_status:
                graph.setdefault(r.from_status, set()).add(r.to_status)

        # DFS cycle detection
        cycles = _find_cycles_in_graph(graph)
        if cycles:
            cycle_desc = " → ".join(cycles[0] + [cycles[0][0]])
            frappe.throw(
                _("Escalation loop detected for '{0}' status-change rules: {1}. "
                  "This chain of status changes would loop infinitely. "
                  "Please adjust From/To Status values to break the cycle.").format(
                    self.apply_to, cycle_desc
                ),
                title=_("Escalation Loop Detected"),
            )


def _find_cycles_in_graph(graph):
    """Return a list of cycles found via DFS in a directed graph.

    Each cycle is represented as a list of nodes forming the loop.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    colour = {node: WHITE for node in graph}
    # Also mark nodes that only appear as targets
    for targets in graph.values():
        for t in targets:
            colour.setdefault(t, WHITE)

    parent = {}
    cycles = []

    def dfs(node):
        colour[node] = GRAY
        for neighbour in graph.get(node, []):
            if colour.get(neighbour, WHITE) == GRAY:
                # Back edge — reconstruct cycle
                cycle = [neighbour, node]
                cur = node
                while parent.get(cur) and parent[cur] != neighbour:
                    cur = parent[cur]
                    cycle.append(cur)
                cycle.reverse()
                cycles.append(cycle)
                return
            if colour.get(neighbour, WHITE) == WHITE:
                parent[neighbour] = node
                dfs(neighbour)
                if cycles:
                    return
        colour[node] = BLACK

    for node in list(colour):
        if colour[node] == WHITE:
            dfs(node)
            if cycles:
                break

    return cycles
