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
		# Copy table structures from main DB
		_copy_tables_mariadb(frappe.conf.db_name, tenant.db_name)
		frappe.db.commit()
	finally:
		frappe.local.db = original_db
		tenant_db.close()


def _install_schema_in_tenant_schema(tenant):
	"""Install frappe tables in a tenant's schema by copying table structure from the main database."""
	db_type = frappe.conf.get("db_type", "mariadb")
	main_db = frappe.conf.db_name
	schema_name = tenant.schema_name

	if db_type == "postgres":
		# PostgreSQL: copy tables via pg_dump --schema-only or CREATE TABLE LIKE
		_copy_tables_postgres(main_db, schema_name)
	else:
		# MariaDB: copy table structures from main DB to tenant DB
		_copy_tables_mariadb(main_db, schema_name)


def _copy_tables_mariadb(main_db, tenant_db):
	"""Copy all table structures AND data from main DB to tenant DB (MariaDB)."""
	# Get all tables from the main database
	tables = frappe.db.sql(
		"SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'",
		(main_db,),
		as_list=True,
	)

	if not tables:
		click.secho("No tables found in main database to copy", fg="yellow")
		return

	# Switch to tenant DB
	frappe.db.sql(f"USE `{tenant_db}`")

	for (table_name,) in tables:
		try:
			# Get CREATE TABLE statement from main DB
			create_stmt = frappe.db.sql(
				f"SHOW CREATE TABLE `{main_db}`.`{table_name}`", as_list=True
			)
			if create_stmt:
				create_sql = create_stmt[0][1]
				# Execute in tenant DB (tables will be created in current USE'd DB)
				frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `{table_name}`")
				frappe.db.sql_ddl(create_sql)
				# Copy data from main DB to tenant DB
				try:
					frappe.db.sql(
						f"INSERT INTO `{tenant_db}`.`{table_name}` SELECT * FROM `{main_db}`.`{table_name}`"
					)
				except Exception as data_err:
					click.secho(f"  Warning: could not copy data for {table_name}: {data_err}", fg="yellow")
		except Exception as e:
			click.secho(f"  Warning: could not copy table {table_name}: {e}", fg="yellow")

	frappe.db.commit()

	# Switch back to main DB
	frappe.db.sql(f"USE `{frappe.conf.db_name}`")


def _copy_tables_postgres(main_db, schema_name):
	"""Copy all table structures from public schema to tenant schema (PostgreSQL)."""
	tables = frappe.db.sql(
		"SELECT tablename FROM pg_tables WHERE schemaname = 'public'",
		as_list=True,
	)

	for (table_name,) in tables:
		try:
			frappe.db.sql_ddl(
				f'CREATE TABLE IF NOT EXISTS "{schema_name}"."{table_name}" '
				f'(LIKE "public"."{table_name}" INCLUDING ALL)'
			)
		except Exception as e:
			click.secho(f"  Warning: could not copy table {table_name}: {e}", fg="yellow")

	frappe.db.commit()


# ---------------------------------------------------------------------------
# Schema-only sync for migrate (preserves tenant data)
# ---------------------------------------------------------------------------

def _sync_schema_in_tenant_db(tenant):
	"""Sync table structures AND DocType metadata in a tenant's separate database.

	Unlike ``_install_schema_in_tenant_db`` this does NOT drop tables or
	copy data – it only adds missing tables/columns so that tenant data
	is preserved across migrations.  It also syncs DocType metadata rows.
	"""
	from frappe.database import get_db

	tenant_db = get_db(
		socket=frappe.conf.get("db_socket"),
		host=tenant.db_host or frappe.conf.db_host,
		port=tenant.db_port or frappe.conf.db_port,
		user=tenant.db_user or tenant.db_name,
		password=tenant.get_password("db_password") or frappe.conf.db_password,
		cur_db_name=tenant.db_name,
	)

	original_db = frappe.local.db
	frappe.local.db = tenant_db

	try:
		_sync_tables_mariadb(frappe.conf.db_name, tenant.db_name)
		_sync_doctype_metadata(frappe.conf.db_name, tenant.db_name)
		frappe.db.commit()
	finally:
		frappe.local.db = original_db
		tenant_db.close()


def _sync_schema_in_tenant_schema(tenant):
	"""Sync table structures AND DocType metadata in a tenant's schema.

	Preserves existing tenant data — only adds missing tables/columns
	and replaces DocType/DocField/DocPerm metadata so that field
	definitions stay in sync across all tenants.
	"""
	db_type = frappe.conf.get("db_type", "mariadb")
	main_db = frappe.conf.db_name
	schema_name = tenant.schema_name

	if db_type == "postgres":
		_sync_tables_postgres(main_db, schema_name)
	else:
		_sync_tables_mariadb(main_db, schema_name)

	# After table structure is synced, sync DocType metadata rows
	_sync_doctype_metadata(main_db, schema_name)


def _sync_tables_mariadb(main_db, tenant_db):
	"""Sync table structures from main DB to tenant DB (MariaDB).

	For each table in the main database:
	- If the table does not exist in the tenant DB: create it (structure only, no data).
	- If the table exists: add any missing columns and update changed column types.

	Existing tenant data is never dropped or overwritten.
	"""
	# Get all tables from the main database
	main_tables = frappe.db.sql(
		"SELECT TABLE_NAME FROM information_schema.TABLES "
		"WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'",
		(main_db,),
		as_list=True,
	)

	if not main_tables:
		click.secho("No tables found in main database to sync", fg="yellow")
		return

	# Get existing tables in tenant DB
	tenant_tables_result = frappe.db.sql(
		"SELECT TABLE_NAME FROM information_schema.TABLES "
		"WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'",
		(tenant_db,),
		as_list=True,
	)
	existing_tenant_tables = {row[0] for row in tenant_tables_result}

	# Switch to tenant DB
	frappe.db.sql(f"USE `{tenant_db}`")

	for (table_name,) in main_tables:
		try:
			if table_name not in existing_tenant_tables:
				# Table doesn't exist in tenant — create structure only (no data)
				create_stmt = frappe.db.sql(
					f"SHOW CREATE TABLE `{main_db}`.`{table_name}`", as_list=True
				)
				if create_stmt:
					frappe.db.sql_ddl(create_stmt[0][1])
			else:
				# Table exists — sync columns
				_sync_columns_mariadb(main_db, tenant_db, table_name)
		except Exception as e:
			click.secho(f"  Warning: could not sync table {table_name}: {e}", fg="yellow")

	frappe.db.commit()

	# Switch back to main DB
	frappe.db.sql(f"USE `{frappe.conf.db_name}`")


def _sync_columns_mariadb(main_db, tenant_db, table_name):
	"""Sync columns of a single table from main DB to tenant DB (MariaDB).

	Adds missing columns and modifies columns whose type/default has changed.
	Never drops columns to avoid accidental data loss.
	"""
	# Fetch columns from main DB
	main_columns = frappe.db.sql(
		"SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, EXTRA, "
		"       ORDINAL_POSITION "
		"FROM information_schema.COLUMNS "
		"WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
		"ORDER BY ORDINAL_POSITION",
		(main_db, table_name),
		as_dict=True,
	)

	# Fetch columns from tenant DB
	tenant_columns = frappe.db.sql(
		"SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, EXTRA "
		"FROM information_schema.COLUMNS "
		"WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
		(tenant_db, table_name),
		as_dict=True,
	)
	tenant_col_map = {c["COLUMN_NAME"]: c for c in tenant_columns}

	prev_col = None
	for col in main_columns:
		col_name = col["COLUMN_NAME"]
		col_type = col["COLUMN_TYPE"]
		nullable = "NULL" if col["IS_NULLABLE"] == "YES" else "NOT NULL"
		default = _build_default_clause(col["COLUMN_DEFAULT"])
		extra = col.get("EXTRA") or ""

		if col_name not in tenant_col_map:
			# Column missing in tenant — add it
			position = f"AFTER `{prev_col}`" if prev_col else "FIRST"
			frappe.db.sql_ddl(
				f"ALTER TABLE `{table_name}` ADD COLUMN `{col_name}` {col_type} "
				f"{nullable} {default} {extra} {position}"
			)
		else:
			# Column exists — check if definition changed
			t_col = tenant_col_map[col_name]
			if (
				t_col["COLUMN_TYPE"] != col_type
				or t_col["IS_NULLABLE"] != col["IS_NULLABLE"]
				or t_col["COLUMN_DEFAULT"] != col["COLUMN_DEFAULT"]
			):
				frappe.db.sql_ddl(
					f"ALTER TABLE `{table_name}` MODIFY COLUMN `{col_name}` {col_type} "
					f"{nullable} {default} {extra}"
				)

		prev_col = col_name


def _sync_doctype_metadata(main_db, tenant_db):
	"""Sync DocType metadata rows from the main DB to the tenant DB.

	This ensures that every tenant has up-to-date DocType, DocField,
	DocPerm (and related child-table) records so that Frappe's metadata
	cache (``get_meta``) returns the correct field list.

	Only *system* metadata tables are synced — tenant user-data tables
	are never touched.
	"""
	# The metadata tables that must be identical across all tenants.
	# Each entry is (table_name, parent_column_or_None).
	# When parent_column is given, only rows whose parent appears in
	# `tabDocType` are synced (i.e. DocType children).
	METADATA_TABLES = [
		("tabDocType", None),
		("tabDocField", "parent"),
		("tabDocPerm", "parent"),
		("tabDocType Action", "parent"),
		("tabDocType Link", "parent"),
		("tabDocType State", "parent"),
	]

	# Make sure we're operating on the main DB to read source data
	frappe.db.sql(f"USE `{main_db}`")

	# Get the list of all DocTypes in the main DB
	all_doctypes = frappe.db.sql(
		f"SELECT name FROM `{main_db}`.`tabDocType`", as_list=True
	)
	if not all_doctypes:
		return

	dt_names = [row[0] for row in all_doctypes]

	for table_name, parent_col in METADATA_TABLES:
		# Check that the table exists in both main and tenant
		main_exists = frappe.db.sql(
			"SELECT 1 FROM information_schema.TABLES "
			"WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s LIMIT 1",
			(main_db, table_name),
		)
		tenant_exists = frappe.db.sql(
			"SELECT 1 FROM information_schema.TABLES "
			"WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s LIMIT 1",
			(tenant_db, table_name),
		)
		if not main_exists or not tenant_exists:
			continue

		if parent_col:
			# Child table — delete tenant rows for known DocTypes, then re-insert from main
			# Process in batches to avoid overly-long IN clauses
			batch_size = 100
			for i in range(0, len(dt_names), batch_size):
				batch = dt_names[i : i + batch_size]
				placeholders = ", ".join(["%s"] * len(batch))
				frappe.db.sql(
					f"DELETE FROM `{tenant_db}`.`{table_name}` "
					f"WHERE `{parent_col}` IN ({placeholders})",
					tuple(batch),
				)
				frappe.db.sql(
					f"INSERT INTO `{tenant_db}`.`{table_name}` "
					f"SELECT * FROM `{main_db}`.`{table_name}` "
					f"WHERE `{parent_col}` IN ({placeholders})",
					tuple(batch),
				)
		else:
			# Root table (tabDocType) — full replace
			frappe.db.sql(f"DELETE FROM `{tenant_db}`.`{table_name}`")
			frappe.db.sql(
				f"INSERT INTO `{tenant_db}`.`{table_name}` "
				f"SELECT * FROM `{main_db}`.`{table_name}`"
			)

	frappe.db.commit()


def _build_default_clause(default_value):
	"""Build a DEFAULT clause from an information_schema COLUMN_DEFAULT value."""
	if default_value is None:
		return ""
	# current_timestamp and similar expressions should not be quoted
	if default_value.upper() in ("CURRENT_TIMESTAMP", "NULL"):
		return f"DEFAULT {default_value}"
	return f"DEFAULT '{default_value}'"


def _sync_tables_postgres(main_db, schema_name):
	"""Sync table structures from public schema to tenant schema (PostgreSQL).

	Creates missing tables and adds missing columns.  Never drops data.
	"""
	# Get tables in public schema
	main_tables = frappe.db.sql(
		"SELECT tablename FROM pg_tables WHERE schemaname = 'public'",
		as_list=True,
	)

	# Get existing tables in tenant schema
	tenant_tables_result = frappe.db.sql(
		"SELECT tablename FROM pg_tables WHERE schemaname = %s",
		(schema_name,),
		as_list=True,
	)
	existing = {r[0] for r in tenant_tables_result}

	for (table_name,) in main_tables:
		try:
			if table_name not in existing:
				frappe.db.sql_ddl(
					f'CREATE TABLE IF NOT EXISTS "{schema_name}"."{table_name}" '
					f'(LIKE "public"."{table_name}" INCLUDING ALL)'
				)
			else:
				# Add missing columns
				main_cols = frappe.db.sql(
					"SELECT column_name, data_type, is_nullable, column_default "
					"FROM information_schema.columns "
					"WHERE table_schema = 'public' AND table_name = %s",
					(table_name,),
					as_dict=True,
				)
				tenant_cols = frappe.db.sql(
					"SELECT column_name FROM information_schema.columns "
					"WHERE table_schema = %s AND table_name = %s",
					(schema_name, table_name),
					as_dict=True,
				)
				existing_cols = {c["column_name"] for c in tenant_cols}
				for c in main_cols:
					if c["column_name"] not in existing_cols:
						null_clause = "" if c["is_nullable"] == "YES" else "NOT NULL"
						default_clause = f"DEFAULT {c['column_default']}" if c["column_default"] else ""
						frappe.db.sql_ddl(
							f'ALTER TABLE "{schema_name}"."{table_name}" '
							f'ADD COLUMN "{c["column_name"]}" {c["data_type"]} '
							f'{null_clause} {default_clause}'
						)
		except Exception as e:
			click.secho(f"  Warning: could not sync table {table_name}: {e}", fg="yellow")

	frappe.db.commit()


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
