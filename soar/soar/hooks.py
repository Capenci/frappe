app_name = "soar"
app_title = "SOAR"
app_publisher = "SOAR Team"
app_description = "Security Orchestration, Automation and Response"
app_email = "soar@example.com"
app_license = "MIT"
required_apps = ["frappe"]

after_install = "soar.install.after_install"

# ---------- Doc Events ----------
doc_events = {
    "SOAR Alert": {
        "validate": "soar.services.escalation_service.validate_status_change",
        "on_update": [
            "soar.services.sla_service.apply_sla_on_update",
            "soar.services.escalation_service.check_auto_escalation",
            "soar.services.playbook_engine.trigger_on_event",
        ],
        "after_insert": [
            "soar.services.sla_service.apply_sla_on_create",
            "soar.services.playbook_engine.trigger_on_event",
        ],
    },
    "SOAR Case": {
        "validate": "soar.services.escalation_service.validate_status_change",
        "on_update": [
            "soar.services.sla_service.apply_sla_on_update",
            "soar.services.escalation_service.check_auto_escalation",
            "soar.services.playbook_engine.trigger_on_event",
        ],
        "after_insert": [
            "soar.services.sla_service.apply_sla_on_create",
            "soar.services.playbook_engine.trigger_on_event",
        ],
    },
    "SOAR Incident": {
        "validate": "soar.services.escalation_service.validate_status_change",
        "on_update": [
            "soar.services.sla_service.apply_sla_on_update",
            "soar.services.escalation_service.check_auto_escalation",
            "soar.services.playbook_engine.trigger_on_event",
        ],
        "after_insert": [
            "soar.services.sla_service.apply_sla_on_create",
            "soar.services.playbook_engine.trigger_on_event",
        ],
    },
}

# ---------- Scheduled Tasks ----------
scheduler_events = {
    "cron": {
        "*/5 * * * *": [
            "soar.services.sla_service.check_sla_breaches",
        ],
        "*/10 * * * *": [
            "soar.services.siem_connector.pull_all_integrations",
        ],
    },
    "daily": [
        "soar.services.escalation_service.run_scheduled_escalations",
        "soar.services.playbook_engine.run_scheduled_playbooks",
    ],
}

# ---------- Fixtures ----------
fixtures = [
    {
        "dt": "Role",
        "filters": [["name", "in", ["SOAR Manager", "SOAR Analyst"]]],
    },
    {
        "dt": "Dashboard Chart",
        "filters": [["module", "in", ["Alert Management", "Case Management", "Incident Management"]]],
    },
    {
        "dt": "Number Card",
        "filters": [["module", "in", ["Alert Management", "Case Management", "Incident Management"]]],
    },
]

app_include_css = "/assets/soar/css/soar.css"
app_include_js = "/assets/soar/js/soar.js"

app_home = "/desk/soar"

add_to_apps_screen = [
    {
        "name": "soar",
        "logo": "/assets/frappe/images/frappe-framework-logo.svg",
        "title": "SOAR",
        "route": "/desk/soar",
    }
]
