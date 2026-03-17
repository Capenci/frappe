# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

"""
CLI commands for multi-tenant management.

Usage:
    bench --site <site> create-tenant <tenant_name> --isolation schema|database [options]
    bench --site <site> remove-tenant <tenant_name>
    bench --site <site> list-tenants
    bench --site <site> add-tenant-user <tenant_name> <user> [--roles '["Role 1"]'] [--default]
    bench --site <site> remove-tenant-user <tenant_name> <user>
    bench --site <site> enable-multi-tenancy
    bench --site <site> disable-multi-tenancy
    bench --site <site> setup-tenant-db <tenant_name> (for database isolation)
    bench --site <site> setup-tenant-schema <tenant_name> (for schema isolation)
"""

import json
import sys

import click

import frappe
from frappe.commands import pass_context


@click.command("enable-multi-tenancy")
@pass_context
def enable_multi_tenancy(context):
	"""Enable multi-tenancy for the site."""
	site = context.sites[0] if context.sites else None
	if not site:
		raise click.UsageError("Please specify a site with --site")

	frappe.init(site)
	frappe.connect()
	try:
		frappe.conf.multi_tenancy_enabled = True
		_update_site_config(site, {"multi_tenancy_enabled": True})
		click.secho(f"Multi-tenancy enabled for {site}", fg="green")
	finally:
		frappe.destroy()


@click.command("disable-multi-tenancy")
@pass_context
def disable_multi_tenancy(context):
	"""Disable multi-tenancy for the site."""
	site = context.sites[0] if context.sites else None
	if not site:
		raise click.UsageError("Please specify a site with --site")

	frappe.init(site)
	frappe.connect()
	try:
		frappe.conf.multi_tenancy_enabled = False
		_update_site_config(site, {"multi_tenancy_enabled": False})
		click.secho(f"Multi-tenancy disabled for {site}", fg="green")
	finally:
		frappe.destroy()


@click.command("create-tenant")
@click.argument("tenant_name")
@click.option("--title", default=None, help="Display title")
@click.option("--isolation", type=click.Choice(["schema", "database"]), required=True, help="Isolation mode")
@click.option("--db-host", default=None, help="Database host (for database isolation)")
@click.option("--db-port", default=None, type=int, help="Database port (for database isolation)")
@click.option("--db-name", default=None, help="Database name (for database isolation) or schema name (for schema isolation)")
@click.option("--db-user", default=None, help="Database user (for database isolation)")
@click.option("--db-password", default=None, help="Database password (for database isolation)")
@click.option("--domain", default=None, help="Domain for this tenant")
@click.option("--default", "is_default", is_flag=True, help="Set as default tenant")
@pass_context
def create_tenant(context, tenant_name, title, isolation, db_host, db_port, db_name, db_user, db_password, domain, is_default):
	"""Create a new tenant."""
	site = context.sites[0] if context.sites else None
	if not site:
		raise click.UsageError("Please specify a site with --site")

	frappe.init(site)
	frappe.connect()
	try:
		doc = frappe.new_doc("Tenant")
		doc.tenant_name = tenant_name
		doc.title = title or tenant_name
		doc.isolation_mode = isolation
		doc.enabled = 1
		doc.default_for_site = 1 if is_default else 0

		if isolation == "database":
			doc.db_name = db_name or f"{frappe.conf.db_name}_{tenant_name}"
			doc.db_host = db_host
			doc.db_port = db_port
			doc.db_user = db_user
			doc.db_password = db_password
		elif isolation == "schema":
			doc.schema_name = db_name or f"{frappe.conf.db_name}_{tenant_name}"

		if domain:
			doc.domain = domain

		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		click.secho(f"Tenant '{tenant_name}' created successfully", fg="green")
	except Exception as e:
		click.secho(f"Error creating tenant: {e}", fg="red")
		sys.exit(1)
	finally:
		frappe.destroy()


@click.command("remove-tenant")
@click.argument("tenant_name")
@click.option("--force", is_flag=True, help="Force remove even if users exist")
@pass_context
def remove_tenant(context, tenant_name, force):
	"""Remove a tenant."""
	site = context.sites[0] if context.sites else None
	if not site:
		raise click.UsageError("Please specify a site with --site")

	frappe.init(site)
	frappe.connect()
	try:
		if force:
			# Remove all tenant users first
			for tu in frappe.get_all("Tenant User", filters={"tenant": tenant_name}):
				frappe.delete_doc("Tenant User", tu.name, ignore_permissions=True)

		frappe.delete_doc("Tenant", tenant_name, ignore_permissions=True)
		frappe.db.commit()
		click.secho(f"Tenant '{tenant_name}' removed", fg="green")
	except Exception as e:
		click.secho(f"Error removing tenant: {e}", fg="red")
		sys.exit(1)
	finally:
		frappe.destroy()


@click.command("list-tenants")
@pass_context
def list_tenants(context):
	"""List all tenants."""
	site = context.sites[0] if context.sites else None
	if not site:
		raise click.UsageError("Please specify a site with --site")

	frappe.init(site)
	frappe.connect()
	try:
		tenants = frappe.get_all(
			"Tenant",
			fields=["name", "title", "enabled", "isolation_mode", "default_for_site", "domain"],
			order_by="name",
		)
		if not tenants:
			click.echo("No tenants found.")
			return

		click.echo(f"\n{'Name':<20} {'Title':<25} {'Mode':<10} {'Enabled':<8} {'Default':<8} {'Domain':<30}")
		click.echo("-" * 101)
		for t in tenants:
			click.echo(
				f"{t.name:<20} {t.title:<25} {t.isolation_mode:<10} "
				f"{'Yes' if t.enabled else 'No':<8} {'Yes' if t.default_for_site else 'No':<8} "
				f"{t.domain or '':<30}"
			)
		click.echo()
	finally:
		frappe.destroy()


@click.command("add-tenant-user")
@click.argument("tenant_name")
@click.argument("user_email")
@click.option("--roles", default=None, help='JSON array of roles, e.g. \'["System Manager", "HR Manager"]\'')
@click.option("--default", "is_default", is_flag=True, help="Set as user's default tenant")
@pass_context
def add_tenant_user(context, tenant_name, user_email, roles, is_default):
	"""Add a user to a tenant."""
	site = context.sites[0] if context.sites else None
	if not site:
		raise click.UsageError("Please specify a site with --site")

	frappe.init(site)
	frappe.connect()
	try:
		# Validate roles JSON
		if roles:
			try:
				json.loads(roles)
			except json.JSONDecodeError:
				click.secho("Invalid roles JSON", fg="red")
				sys.exit(1)

		doc = frappe.new_doc("Tenant User")
		doc.tenant = tenant_name
		doc.user = user_email
		doc.enabled = 1
		doc.is_default = 1 if is_default else 0
		doc.roles = roles

		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		click.secho(f"User '{user_email}' added to tenant '{tenant_name}'", fg="green")
	except Exception as e:
		click.secho(f"Error: {e}", fg="red")
		sys.exit(1)
	finally:
		frappe.destroy()


@click.command("remove-tenant-user")
@click.argument("tenant_name")
@click.argument("user_email")
@pass_context
def remove_tenant_user(context, tenant_name, user_email):
	"""Remove a user from a tenant."""
	site = context.sites[0] if context.sites else None
	if not site:
		raise click.UsageError("Please specify a site with --site")

	frappe.init(site)
	frappe.connect()
	try:
		tu = frappe.db.get_value("Tenant User", {"tenant": tenant_name, "user": user_email}, "name")
		if not tu:
			click.secho(f"User '{user_email}' is not in tenant '{tenant_name}'", fg="yellow")
			return

		frappe.delete_doc("Tenant User", tu, ignore_permissions=True)
		frappe.db.commit()
		click.secho(f"User '{user_email}' removed from tenant '{tenant_name}'", fg="green")
	except Exception as e:
		click.secho(f"Error: {e}", fg="red")
		sys.exit(1)
	finally:
		frappe.destroy()


@click.command("setup-tenant-db")
@click.argument("tenant_name")
@click.option("--root-login", default="root", help="Database root login")
@click.option("--root-password", prompt=True, hide_input=True, help="Database root password")
@pass_context
def setup_tenant_db(context, tenant_name, root_login, root_password):
	"""Create the database and schema for a tenant with database isolation."""
	site = context.sites[0] if context.sites else None
	if not site:
		raise click.UsageError("Please specify a site with --site")

	frappe.init(site)
	frappe.connect()
	try:
		tenant = frappe.get_doc("Tenant", tenant_name)
		if tenant.isolation_mode != "database":
			click.secho("This command is for database isolation mode only", fg="red")
			sys.exit(1)

		from frappe.database import get_db
		root_db = get_db(
			host=tenant.db_host or frappe.conf.db_host,
			port=tenant.db_port or frappe.conf.db_port,
			user=root_login,
			password=root_password,
			cur_db_name="",
		)

		from frappe.database.db_manager import DbManager
		manager = DbManager(root_db)

		db_name = tenant.db_name
		db_user = tenant.db_user or db_name
		db_password = tenant.get_password("db_password") or frappe.conf.db_password

		click.echo(f"Creating database '{db_name}'...")
		manager.create_database(db_name)
		manager.create_user(db_user, db_password)
		manager.grant_all_privileges(db_name, db_user)
		manager.flush_privileges()
		root_db.close()

		click.secho(f"Database '{db_name}' created and configured for tenant '{tenant_name}'", fg="green")

		# Now install frappe schema in the tenant database
		click.echo("Installing schema in tenant database...")
		_install_schema_in_tenant_db(tenant)
		click.secho("Schema installed successfully", fg="green")

	except Exception as e:
		click.secho(f"Error: {e}", fg="red")
		sys.exit(1)
	finally:
		frappe.destroy()


@click.command("setup-tenant-schema")
@click.argument("tenant_name")
@click.option("--root-login", default="root", help="Database root login")
@click.option("--root-password", prompt=True, hide_input=True, help="Database root password")
@pass_context
def setup_tenant_schema(context, tenant_name, root_login, root_password):
	"""Create the schema for a tenant with schema isolation."""
	site = context.sites[0] if context.sites else None
	if not site:
		raise click.UsageError("Please specify a site with --site")

	frappe.init(site)
	frappe.connect()
	try:
		tenant = frappe.get_doc("Tenant", tenant_name)
		if tenant.isolation_mode != "schema":
			click.secho("This command is for schema isolation mode only", fg="red")
			sys.exit(1)

		schema_name = tenant.schema_name
		db_type = frappe.conf.get("db_type", "mariadb")

		if db_type == "postgres":
			frappe.db.sql(f"CREATE SCHEMA IF NOT EXISTS {frappe.db.escape(schema_name)}")
		else:
			# MariaDB: create a separate database for the schema
			from frappe.database import get_db
			root_db = get_db(
				host=frappe.conf.db_host,
				port=frappe.conf.db_port,
				user=root_login,
				password=root_password,
				cur_db_name="",
			)
			from frappe.database.db_manager import DbManager
			manager = DbManager(root_db)
			manager.create_database(schema_name)
			manager.grant_all_privileges(schema_name, frappe.conf.db_user)
			manager.flush_privileges()
			root_db.close()

		frappe.db.commit()
		click.secho(f"Schema '{schema_name}' created for tenant '{tenant_name}'", fg="green")

		# Install frappe tables in the schema
		click.echo("Installing schema tables...")
		_install_schema_in_tenant_schema(tenant)
		click.secho("Schema tables installed successfully", fg="green")

	except Exception as e:
		click.secho(f"Error: {e}", fg="red")
		sys.exit(1)
	finally:
		frappe.destroy()


def _install_schema_in_tenant_db(tenant):
	"""Install frappe DocType tables in a tenant's separate database."""
	from frappe.database import get_db

	tenant_db = get_db(
		socket=frappe.conf.get("db_socket"),
		host=tenant.db_host or frappe.conf.db_host,
		port=tenant.db_port or frappe.conf.db_port,
		user=tenant.db_user or tenant.db_name,
		password=tenant.get_password("db_password") or frappe.conf.db_password,
		cur_db_name=tenant.db_name,
	)

	# Store current db and swap
	original_db = frappe.local.db
	frappe.local.db = tenant_db

	try:
		from frappe.installer import install_db
		# Sync all doctypes to create tables
		from frappe.modules.utils import sync_for
		for app in frappe.get_installed_apps():
			sync_for(app, force=True, reset_permissions=True)
		frappe.db.commit()
	finally:
		frappe.local.db = original_db
		tenant_db.close()


def _install_schema_in_tenant_schema(tenant):
	"""Install frappe tables in a tenant's schema."""
	from frappe.multi_tenancy.tenant_manager import _switch_to_tenant_schema

	original_schema = getattr(frappe.local, "tenant_schema", None)
	_switch_to_tenant_schema({"schema_name": tenant.schema_name, "isolation_mode": "schema"})

	try:
		from frappe.modules.utils import sync_for
		for app in frappe.get_installed_apps():
			sync_for(app, force=True, reset_permissions=True)
		frappe.db.commit()
	finally:
		# Switch back
		db_type = frappe.conf.get("db_type", "mariadb")
		if db_type == "postgres":
			frappe.db.sql("SET search_path TO public")
		else:
			frappe.db.sql(f"USE `{frappe.conf.db_name}`")
		if original_schema:
			frappe.local.tenant_schema = original_schema
		elif hasattr(frappe.local, "tenant_schema"):
			del frappe.local.tenant_schema


def _update_site_config(site, updates):
	"""Update site_config.json with the given key-value pairs."""
	import os
	config_path = os.path.join(frappe.local.sites_path, site, "site_config.json")
	config = {}
	if os.path.exists(config_path):
		config = frappe.get_file_json(config_path)
	config.update(updates)
	with open(config_path, "w") as f:
		f.write(frappe.as_json(config))


commands = [
	enable_multi_tenancy,
	disable_multi_tenancy,
	create_tenant,
	remove_tenant,
	list_tenants,
	add_tenant_user,
	remove_tenant_user,
	setup_tenant_db,
	setup_tenant_schema,
]
