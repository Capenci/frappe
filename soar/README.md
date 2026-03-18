# SOAR - Security Orchestration, Automation and Response

A comprehensive SOAR platform built on the Frappe Framework.

## Features

- **Alert Management** — CRUD, evidence upload/removal, status changes, webhook ingestion, SIEM integration (Wazuh, Splunk, Elastic, QRadar)
- **Case Management** — CRUD, assign/unassign alerts to cases, status tracking, evidence management
- **Incident Management** — Group cases into incidents, status lifecycle tracking
- **Escalation** — Rule-based status change approval/denial, role-based escalation, automatic escalation with conditions, event/manual/scheduled triggers
- **SLA** — Auto breach/warning on alerts, cases, and incidents based on configurable policies
- **Playbook** — DAG-based automation with sequential and concurrent node execution. Trigger by event, manual, or scheduler. Ingest data from alerts/cases/incidents as input
- **Reports** — Alert summary, case summary, SLA compliance reports
- **Dashboard** — Real-time operational dashboard

## Installation

```bash
bench get-app soar
bench --site your-site install-app soar
```

## Roles

- **SOAR Manager** — Full access to all SOAR modules
- **SOAR Analyst** — Create/manage alerts, cases; read access to incidents, playbooks

## License

MIT
