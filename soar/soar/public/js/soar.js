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
