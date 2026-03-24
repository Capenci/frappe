// Copyright (c) 2025, SOAR Team and contributors
// For license information, please see license.txt

frappe.ui.form.on("SOAR Escalation Rule", {
	refresh(frm) {
		frm.trigger("toggle_trigger_fields");
	},

	trigger_type(frm) {
		frm.trigger("toggle_trigger_fields");
	},

	toggle_trigger_fields(frm) {
		const trigger = frm.doc.trigger_type;

		// Clear irrelevant fields when trigger type changes
		if (trigger !== "On Status Change") {
			frm.set_value("from_status", "");
			frm.set_value("to_status", "");
		}
		if (trigger !== "On Event") {
			frm.set_value("event_type", "");
		}
		if (trigger !== "Scheduled") {
			frm.set_value("schedule", "");
		}

		// Toggle field descriptions based on event type
		if (trigger === "On Event") {
			frm.set_df_property(
				"event_type",
				"description",
				__("Select the event that will trigger this escalation rule. "
				   + "For SLA events, the rule fires when the SLA service detects a breach or warning.")
			);
		}
	},
});
