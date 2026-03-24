frappe.ui.form.on("SOAR Case", {
	refresh(frm) {
		const _colors = (typeof soar !== "undefined" && soar.severity_colors) || {};
		frm.page.set_indicator(frm.doc.status, _colors[frm.doc.severity] || "grey");

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

			// Assign Alert
			frm.add_custom_button(__("Assign Alert"), () => {
				frappe.prompt(
					{
						fieldname: "alert",
						fieldtype: "Link",
						options: "SOAR Alert",
						label: __("Alert"),
						reqd: 1,
					},
					(values) => {
						frm.call("assign_alert", { alert_name: values.alert }).then(() =>
							frm.reload_doc()
						);
					}
				);
			}, __("Actions"));

			// Add Evidence
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

			// Quick status change
			const transitions = {
				"New": ["Open"],
				"Open": ["In Progress"],
				"In Progress": ["Resolved"],
				"Resolved": ["Closed"],
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
							trigger_doctype: "SOAR Case",
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
