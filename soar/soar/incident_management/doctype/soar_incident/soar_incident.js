frappe.ui.form.on("SOAR Incident", {
	refresh(frm) {
		frm.page.set_indicator(frm.doc.status, soar.severity_colors[frm.doc.severity] || "grey");

		if (frm.doc.sla_status === "Breached") {
			frm.dashboard.set_headline(
				__('<span class="soar-sla-breached">SLA BREACHED</span>')
			);
		} else if (frm.doc.sla_status === "Warning") {
			frm.dashboard.set_headline(
				__('<span class="soar-sla-warning">SLA Warning</span>')
			);
		}

		if (!frm.is_new()) {
			// Add Case
			frm.add_custom_button(__("Add Case"), () => {
				frappe.prompt(
					{
						fieldname: "case",
						fieldtype: "Link",
						options: "SOAR Case",
						label: __("Case"),
						reqd: 1,
					},
					(values) => {
						frm.call("add_case", { case_name: values.case }).then(() =>
							frm.reload_doc()
						);
					}
				);
			}, __("Actions"));

			// Quick status change
			const transitions = {
				"New": ["Open"],
				"Open": ["In Progress"],
				"In Progress": ["Contained"],
				"Contained": ["Eradicated"],
				"Eradicated": ["Recovered"],
				"Recovered": ["Closed"],
			};

			(transitions[frm.doc.status] || []).forEach((status) => {
				frm.add_custom_button(__(status), () => {
					frm.call("change_status", { new_status: status }).then(() =>
						frm.reload_doc()
					);
				}, __("Change Status"));
			});

			// Run Playbook
			frm.add_custom_button(__("Run Playbook"), () => {
				frappe.prompt(
					{
						fieldname: "playbook",
						fieldtype: "Link",
						options: "SOAR Playbook",
						label: __("Playbook"),
						reqd: 1,
						get_query: () => ({
							filters: { is_active: 1, trigger_type: "Manual" },
						}),
					},
					(values) => {
						frappe.xcall("soar.api.playbook.execute_playbook", {
							playbook_name: values.playbook,
							trigger_doctype: "SOAR Incident",
							trigger_docname: frm.doc.name,
						}).then((r) => {
							frappe.set_route("Form", "SOAR Playbook Execution", r.execution);
						});
					}
				);
			}, __("Actions"));
		}
	},
});
