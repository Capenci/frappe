frappe.ui.form.on("SOAR SIEM Integration", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Test Connection"), () => {
				frm.call("test_connection").then((r) => {
					if (r.message && r.message.status === "ok") {
						frappe.show_alert({ message: __("Connection successful"), indicator: "green" });
					} else {
						frappe.show_alert({
							message: __("Connection failed: {0}", [r.message?.message || "Unknown error"]),
							indicator: "red",
						});
					}
				});
			});

			frm.add_custom_button(__("Pull Now"), () => {
				frm.call("pull_now").then((r) => {
					frappe.show_alert({
						message: __("{0} alerts created", [r.message?.alerts_created || 0]),
						indicator: "green",
					});
				});
			});
		}
	},
});
