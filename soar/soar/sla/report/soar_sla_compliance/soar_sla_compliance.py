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
		{"fieldname": "within_sla", "label": "Within SLA", "fieldtype": "Int", "width": 100},
		{"fieldname": "warning", "label": "Warning", "fieldtype": "Int", "width": 80},
		{"fieldname": "breached", "label": "Breached", "fieldtype": "Int", "width": 80},
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
				SUM(CASE WHEN sla_status = 'Within SLA' THEN 1 ELSE 0 END) as within_sla,
				SUM(CASE WHEN sla_status = 'Warning' THEN 1 ELSE 0 END) as warning,
				SUM(CASE WHEN sla_status = 'Breached' THEN 1 ELSE 0 END) as breached
			FROM `tab{dt}`
			{conditions}
			""",
			values,
			as_dict=True,
		)

		if row and row[0]["total"]:
			r = row[0]
			r["doctype"] = dt.replace("SOAR ", "")
			r["compliance_pct"] = round((r["within_sla"] or 0) / r["total"] * 100, 1) if r["total"] else 0
			data.append(r)

	return data


def get_chart(data):
	if not data:
		return None
	return {
		"data": {
			"labels": [d["doctype"] for d in data],
			"datasets": [
				{"name": "Within SLA", "values": [d["within_sla"] or 0 for d in data]},
				{"name": "Warning", "values": [d["warning"] or 0 for d in data]},
				{"name": "Breached", "values": [d["breached"] or 0 for d in data]},
			],
		},
		"type": "bar",
		"colors": ["#29cd42", "#ffa00a", "#ff5858"],
		"barOptions": {"stacked": 1},
	}


def get_summary(data):
	total = sum(d["total"] for d in data) if data else 0
	breached = sum(d["breached"] or 0 for d in data) if data else 0
	compliance = round((total - breached) / total * 100, 1) if total else 0
	return [
		{"value": total, "label": "Total Tracked", "datatype": "Int"},
		{"value": compliance, "label": "Overall Compliance %", "datatype": "Percent", "indicator": "green" if compliance >= 90 else "red"},
		{"value": breached, "label": "Breached", "datatype": "Int", "indicator": "red" if breached else "green"},
	]
