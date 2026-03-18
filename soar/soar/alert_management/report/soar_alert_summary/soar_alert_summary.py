# Copyright (c) 2024, SOAR and contributors
# For license information, please see license.txt

import frappe


def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	chart = get_chart(data)
	return columns, data, None, chart


def get_columns():
	return [
		{"fieldname": "severity", "label": "Severity", "fieldtype": "Data", "width": 120},
		{"fieldname": "new", "label": "New", "fieldtype": "Int", "width": 80},
		{"fieldname": "triaging", "label": "Triaging", "fieldtype": "Int", "width": 80},
		{"fieldname": "in_progress", "label": "In Progress", "fieldtype": "Int", "width": 100},
		{"fieldname": "resolved", "label": "Resolved", "fieldtype": "Int", "width": 80},
		{"fieldname": "closed", "label": "Closed", "fieldtype": "Int", "width": 80},
		{"fieldname": "false_positive", "label": "False Positive", "fieldtype": "Int", "width": 110},
		{"fieldname": "total", "label": "Total", "fieldtype": "Int", "width": 80},
	]


def get_data(filters):
	conditions = ""
	values = {}

	if filters and filters.get("from_date"):
		conditions += " AND creation >= %(from_date)s"
		values["from_date"] = filters["from_date"]
	if filters and filters.get("to_date"):
		conditions += " AND creation <= %(to_date)s"
		values["to_date"] = filters["to_date"]
	if filters and filters.get("source"):
		conditions += " AND source = %(source)s"
		values["source"] = filters["source"]

	rows = frappe.db.sql(
		f"""
		SELECT
			severity,
			SUM(CASE WHEN status = 'New' THEN 1 ELSE 0 END) as `new`,
			SUM(CASE WHEN status = 'Triaging' THEN 1 ELSE 0 END) as triaging,
			SUM(CASE WHEN status = 'In Progress' THEN 1 ELSE 0 END) as in_progress,
			SUM(CASE WHEN status = 'Resolved' THEN 1 ELSE 0 END) as resolved,
			SUM(CASE WHEN status = 'Closed' THEN 1 ELSE 0 END) as closed,
			SUM(CASE WHEN status = 'False Positive' THEN 1 ELSE 0 END) as false_positive,
			COUNT(*) as total
		FROM `tabSOAR Alert`
		WHERE docstatus < 2 {conditions}
		GROUP BY severity
		ORDER BY FIELD(severity, 'Critical', 'High', 'Medium', 'Low', 'Info')
		""",
		values,
		as_dict=True,
	)
	return rows


def get_chart(data):
	if not data:
		return None
	return {
		"data": {
			"labels": [d["severity"] for d in data],
			"datasets": [
				{"name": "New", "values": [d["new"] for d in data]},
				{"name": "In Progress", "values": [d["in_progress"] for d in data]},
				{"name": "Resolved", "values": [d["resolved"] for d in data]},
			],
		},
		"type": "bar",
		"colors": ["#ff5858", "#ffa00a", "#29cd42"],
	}
