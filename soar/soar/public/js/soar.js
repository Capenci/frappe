// SOAR App Client Scripts

frappe.provide("soar");

soar.severity_colors = {
	Critical: "red",
	High: "orange",
	Medium: "yellow",
	Low: "blue",
	Info: "grey",
};

soar.get_severity_indicator = function (severity) {
	let color = soar.severity_colors[severity] || "grey";
	return `<span class="indicator-pill ${color}">${severity}</span>`;
};

/**
 * Add the "Escalate" button to an Alert / Case / Incident form.
 * The button only appears when an escalation_flow is assigned and there
 * is a next level available. It shows a confirmation dialog with flow
 * information before calling the server API.
 */
soar.add_escalate_button = function (frm) {
	if (!frm.doc.escalation_flow) return;

	frappe.xcall(
		"soar.services.escalation_service.get_escalation_flow_info",
		{ doctype: frm.doctype, docname: frm.docname }
	).then((info) => {
		if (!info || !info.flow || !info.enabled) return;
		if (!info.next_level) {
			// Already at max level — show a disabled indicator
			frm.dashboard.add_comment(
				__("Escalation: at highest level ({0}) — {1}", [
					info.current_level,
					info.current_role,
				]),
				"blue",
				true
			);
			return;
		}

		// Build a description of the full flow for the dialog
		let flow_html = info.levels
			.map((l) => {
				let marker = l.level === info.current_level
					? " ◀ current"
					: l.level === info.next_level
						? " ◀ next"
						: "";
				let bold = marker ? "font-weight:bold;" : "";
				return `<li style="${bold}">Level ${l.level}: ${l.label}${marker}</li>`;
			})
			.join("");

		let btn_label = __("Escalate to {0} (Level {1})", [
			info.next_label,
			info.next_level,
		]);

		frm.add_custom_button(btn_label, () => {
			frappe.confirm(
				`<p>${__("Escalate this {0} to the next level?", [frm.doctype])}</p>
				<p><b>${__("Current")}:</b> ${info.current_role || __("None")} (Level ${info.current_level})</p>
				<p><b>${__("Next")}:</b> ${info.next_label} (Level ${info.next_level})</p>
				<hr>
				<p><b>${__("Escalation Flow")}:</b> ${info.flow}</p>
				<ol style="padding-left:1.2em">${flow_html}</ol>`,
				() => {
					frappe.xcall(
						"soar.services.escalation_service.escalate_to_next_level",
						{ doctype: frm.doctype, docname: frm.docname }
					).then(() => {
						frm.reload_doc();
					});
				}
			);
		}, __("Actions"));

		// Make button orange to stand out
		frm.change_custom_button_type(btn_label, __("Actions"), "warning");
	});
};
