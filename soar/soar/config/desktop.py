from frappe import _


def get_data():
    return [
        {
            "module_name": "Alert Management",
            "color": "#e74c3c",
            "icon": "octicon octicon-alert",
            "type": "module",
            "label": _("Alert Management"),
        },
        {
            "module_name": "Case Management",
            "color": "#3498db",
            "icon": "octicon octicon-briefcase",
            "type": "module",
            "label": _("Case Management"),
        },
        {
            "module_name": "Incident Management",
            "color": "#e67e22",
            "icon": "octicon octicon-flame",
            "type": "module",
            "label": _("Incident Management"),
        },
        {
            "module_name": "Escalation",
            "color": "#9b59b6",
            "icon": "octicon octicon-arrow-up",
            "type": "module",
            "label": _("Escalation"),
        },
        {
            "module_name": "SLA",
            "color": "#1abc9c",
            "icon": "octicon octicon-clock",
            "type": "module",
            "label": _("SLA"),
        },
        {
            "module_name": "Playbook",
            "color": "#2ecc71",
            "icon": "octicon octicon-workflow",
            "type": "module",
            "label": _("Playbook"),
        },
    ]
