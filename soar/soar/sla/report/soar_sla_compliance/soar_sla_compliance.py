# Copyright (c) 2024, SOAR and contributors
# For license information, please see license.txt

import frappe


def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	chart = get_chart(data)
	summary = get_summary(data)
	return columns, data, None, chart, summary


def get_columns():
	return [
		{"fieldname": "doctype", "label": "Type", "fieldtype": "Data", "width": 120},
		{"fieldname": "total", "label": "Total", "fieldtype": "Int", "width": 80},
		{"fieldname": "running", "label": "Running", "fieldtype": "Int", "width": 90},
		{"fieldname": "paused", "label": "Paused", "fieldtype": "Int", "width": 80},
		{"fieldname": "completed", "label": "Completed", "fieldtype": "Int", "width": 100},
		{"fieldname": "breached", "label": "Breached", "fieldtype": "Int", "width": 90},
		{"fieldname": "resp_met", "label": "Resp Met", "fieldtype": "Int", "width": 90},
		{"fieldname": "resp_breached", "label": "Resp Breached", "fieldtype": "Int", "width": 110},
		{"fieldname": "resol_met", "label": "Resol Met", "fieldtype": "Int", "width": 100},
		{"fieldname": "resol_breached", "label": "Resol Breached", "fieldtype": "Int", "width": 120},
		{"fieldname": "compliance_pct", "label": "Compliance %", "fieldtype": "Percent", "width": 120},
	]


def get_data(filters):
	data = []
	for dt in ("SOAR Alert", "SOAR Case", "SOAR Incident"):
		conditions = "WHERE sla_policy IS NOT NULL AND sla_policy != ''"
		values = {}

		if filters and filters.get("from_date"):
			conditions += " AND creation >= %(from_date)s"
			values["from_date"] = filters["from_date"]
		if filters and filters.get("to_date"):
			conditions += " AND creation <= %(to_date)s"
			values["to_date"] = filters["to_date"]

		row = frappe.db.sql(
			f"""
			SELECT
				COUNT(*) as total,
				SUM(CASE WHEN sla_status = 'Running' THEN 1 ELSE 0 END) as running,
				SUM(CASE WHEN sla_status = 'Paused' THEN 1 ELSE 0 END) as paused,
				SUM(CASE WHEN sla_status = 'Completed' THEN 1 ELSE 0 END) as completed,
				SUM(CASE WHEN sla_status = 'Breached' THEN 1 ELSE 0 END) as breached,
				SUM(CASE WHEN sla_response_status = 'Met' THEN 1 ELSE 0 END) as resp_met,
				SUM(CASE WHEN sla_response_status = 'Breached' THEN 1 ELSE 0 END) as resp_breached,
				SUM(CASE WHEN sla_resolution_status = 'Met' THEN 1 ELSE 0 END) as resol_met,
				SUM(CASE WHEN sla_resolution_status = 'Breached' THEN 1 ELSE 0 END) as resol_breached
			FROM `tab{dt}`
			{conditions}
			""",
			values,
			as_dict=True,
		)

		if row and row[0]["total"]:
			r = row[0]
			r["doctype"] = dt.replace("SOAR ", "")
			non_breached = (r["running"] or 0) + (r["paused"] or 0) + (r["completed"] or 0)
			r["compliance_pct"] = round(non_breached / r["total"] * 100, 1) if r["total"] else 0
			data.append(r)

	return data


def get_chart(data):
	if not data:
		return None
	return {
		"data": {
			"labels": [d["doctype"] for d in data],
			"datasets": [
				{"name": "Running", "values": [d["running"] or 0 for d in data]},
				{"name": "Paused", "values": [d["paused"] or 0 for d in data]},
				{"name": "Completed", "values": [d["completed"] or 0 for d in data]},
				{"name": "Breached", "values": [d["breached"] or 0 for d in data]},
			],
		},
		"type": "bar",
		"colors": ["#318AD8", "#ffa00a", "#29cd42", "#ff5858"],
		"barOptions": {"stacked": 1},
	}


def get_summary(data):
	total = sum(d["total"] for d in data) if data else 0
	breached = sum(d["breached"] or 0 for d in data) if data else 0
	completed = sum(d["completed"] or 0 for d in data) if data else 0
	resp_breached = sum(d["resp_breached"] or 0 for d in data) if data else 0
	resol_breached = sum(d["resol_breached"] or 0 for d in data) if data else 0
	compliance = round((total - breached) / total * 100, 1) if total else 0
	return [
		{"value": total, "label": "Total Tracked", "datatype": "Int"},
		{"value": completed, "label": "Completed", "datatype": "Int", "indicator": "green"},
		{"value": compliance, "label": "Overall Compliance %", "datatype": "Percent", "indicator": "green" if compliance >= 90 else "red"},
		{"value": breached, "label": "SLA Breached", "datatype": "Int", "indicator": "red" if breached else "green"},
		{"value": resp_breached, "label": "Response Breached", "datatype": "Int", "indicator": "red" if resp_breached else "green"},
		{"value": resol_breached, "label": "Resolution Breached", "datatype": "Int", "indicator": "red" if resol_breached else "green"},
	]
