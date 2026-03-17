// Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
// MIT License. See license.txt

/**
 * Tenant Switcher Dialog
 * Shows when user has access to multiple tenants and wants to switch.
 */

frappe.provide("frappe.multi_tenancy");

frappe.multi_tenancy.TenantSwitcher = class TenantSwitcher {
	constructor() {
		this.show();
	}

	show() {
		let mt = frappe.boot.multi_tenancy;
		if (!mt || !mt.enabled || !mt.tenants || mt.tenants.length <= 1) {
			frappe.msgprint(__("No other tenants available to switch to."));
			return;
		}

		let current = mt.current_tenant;
		let options = mt.tenants.map((t) => ({
			label: `${t.title}${t.tenant === current ? " ✓" : ""}`,
			value: t.tenant,
			description: t.tenant,
		}));

		let d = new frappe.ui.Dialog({
			title: __("Switch Tenant"),
			fields: [
				{
					fieldtype: "HTML",
					options: `<p class="text-muted">${__("You are currently in")} <strong>${current || __("Default")}</strong></p>`,
				},
				{
					fieldname: "tenant",
					fieldtype: "Select",
					label: __("Select Tenant"),
					options: options.map((o) => o.value),
					default: current,
					reqd: 1,
				},
			],
			primary_action_label: __("Switch"),
			primary_action: (values) => {
				if (values.tenant === current) {
					d.hide();
					return;
				}
				d.hide();
				this.switch_tenant(values.tenant);
			},
		});

		// Customize the select to show titles
		let select_field = d.fields_dict.tenant;
		let $select = select_field.$input;
		$select.empty();
		options.forEach((opt) => {
			$select.append(
				$("<option>")
					.val(opt.value)
					.text(opt.label)
			);
		});
		if (current) {
			$select.val(current);
		}

		d.show();
	}

	switch_tenant(tenant_name) {
		frappe.show_alert({ message: __("Switching tenant..."), indicator: "blue" });

		frappe.xcall("frappe.multi_tenancy.api.switch_tenant", {
			tenant_name: tenant_name,
		}).then((r) => {
			if (r && r.success) {
				frappe.show_alert({
					message: r.message || __("Tenant switched successfully"),
					indicator: "green",
				});
				// Set cookie for immediate subsequent requests
				document.cookie = `frappe_tenant=${tenant_name};path=/;SameSite=Lax`;
				// Reload to apply new tenant context
				setTimeout(() => {
					window.location.reload();
				}, 500);
			}
		}).catch((err) => {
			frappe.show_alert({
				message: __("Failed to switch tenant"),
				indicator: "red",
			});
		});
	}
};

/**
 * Get the current tenant name
 */
frappe.multi_tenancy.get_current = function () {
	let mt = frappe.boot.multi_tenancy;
	return mt && mt.enabled ? mt.current_tenant : null;
};

/**
 * Check if multi-tenancy is enabled
 */
frappe.multi_tenancy.is_enabled = function () {
	let mt = frappe.boot.multi_tenancy;
	return mt && mt.enabled;
};

/**
 * Get list of user's tenants
 */
frappe.multi_tenancy.get_tenants = function () {
	let mt = frappe.boot.multi_tenancy;
	return mt && mt.enabled ? mt.tenants || [] : [];
};
