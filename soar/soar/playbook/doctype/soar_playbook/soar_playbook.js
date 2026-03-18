frappe.ui.form.on("SOAR Playbook", {
	refresh(frm) {
		if (!frm.is_new() && frm.doc.is_active) {
			frm.add_custom_button(__("Execute Now"), () => {
				frappe.confirm(
					__("Execute playbook <b>{0}</b> now?", [frm.doc.title]),
					() => {
						frm.call("execute").then((r) => {
							if (r.message) {
								frappe.set_route("Form", "SOAR Playbook Execution", r.message);
							}
						});
					}
				);
			}, __("Actions"));

			// Show recent executions
			frm.add_custom_button(__("View Executions"), () => {
				frappe.set_route("List", "SOAR Playbook Execution", {
					playbook: frm.doc.name,
				});
			}, __("Actions"));
		}
	},

	validate(frm) {
		// Ensure node IDs are unique
		let ids = new Set();
		(frm.doc.nodes || []).forEach((row) => {
			if (ids.has(row.node_id)) {
				frappe.throw(__("Duplicate Node ID: {0}", [row.node_id]));
			}
			ids.add(row.node_id);
		});
	},
});
