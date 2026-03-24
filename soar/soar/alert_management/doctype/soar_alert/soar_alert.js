frappe.ui.form.on("SOAR Alert", {
	refresh(frm) {
		// Status indicator
		const _colors = (typeof soar !== "undefined" && soar.severity_colors) || {};
		frm.page.set_indicator(frm.doc.status, _colors[frm.doc.severity] || "grey");

		// SLA indicator
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
			// Escalate button
			if (typeof soar !== "undefined" && soar.add_escalate_button) {
				soar.add_escalate_button(frm);
			}

			// Add Evidence button
			frm.add_custom_button(__("Add Evidence"), () => {
				new frappe.ui.FileUploader({
					doctype: frm.doctype,
					docname: frm.docname,
					on_success(file) {
						frm.call("add_evidence", {
							file_url: file.file_url,
							description: "",
						}).then(() => frm.reload_doc());
					},
				});
			}, __("Actions"));

			// Assign to Case button
			if (!frm.doc.case) {
				frm.add_custom_button(__("Assign to Case"), () => {
					frappe.prompt(
						{
							fieldname: "case",
							fieldtype: "Link",
							options: "SOAR Case",
							label: __("Case"),
							reqd: 1,
						},
						(values) => {
							frappe.xcall("soar.case_management.doctype.soar_case.soar_case.SOARCase.assign_alert", {
								doc: values.case,
								alert_name: frm.doc.name,
							}).then(() => frm.reload_doc());
						}
					);
				}, __("Actions"));
			}

			// Quick status change buttons
			const status_transitions = {
				"New": ["Triaging"],
				"Triaging": ["In Progress", "False Positive"],
				"In Progress": ["Resolved"],
				"Resolved": ["Closed"],
			};

			const next_statuses = status_transitions[frm.doc.status] || [];
			next_statuses.forEach((status) => {
				frm.add_custom_button(__(status), () => {
					frm.call("change_status", { new_status: status }).then(() => frm.reload_doc());
				}, __("Change Status"));
			});

			// Run Playbook button
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
							trigger_doctype: "SOAR Alert",
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
