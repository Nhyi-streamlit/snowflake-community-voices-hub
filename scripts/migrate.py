"""Apply workflow migrations to a target schema.

Usage:
  python scripts/migrate.py --connection <name> --schema DB.SCHEMA [--dry-run]

Use an admin role to run this once; the app itself should connect as a separate
least-privilege service user (see migrations/000_service_identity.sql.template).
"""
import argparse
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--connection", required=True)
    p.add_argument("--schema", required=True, help="DB.SCHEMA")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_$]+\.[A-Za-z0-9_$]+", a.schema):
        sys.exit("--schema must be DB.SCHEMA (unquoted identifiers)")
    files = sorted(glob.glob(os.path.join(ROOT, "migrations", "*.sql")))
    if a.dry_run:
        print(f"Would apply to {a.schema}: {[os.path.basename(f) for f in files]}")
        return
    import snowflake.connector
    conn = snowflake.connector.connect(connection_name=a.connection)
    try:
        conn.cursor().execute(f"USE SCHEMA {a.schema}")
        for f in files:
            with open(f) as fh:
                conn.execute_string(fh.read())
            print(f"applied {os.path.basename(f)}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
