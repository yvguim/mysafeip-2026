"""
Migration script for MySafeIP v2.x
Adds IP and instant link expiration fields to existing databases.

Usage:
    python migrate.py
"""

import sys

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from settings import settings


def migrate():
    db_url = settings.SQLALCHEMY_DATABASE_URI
    engine = create_engine(db_url)

    with engine.connect() as conn:
        # Check if columns exist in users table
        result = conn.execute(text("PRAGMA table_info(users)"))
        user_columns = [row[1] for row in result.fetchall()]

        if "ip_default_ttl_hours" not in user_columns:
            conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN ip_default_ttl_hours INTEGER DEFAULT 1"
                )
            )
            print("[+] Added ip_default_ttl_hours to users table")
        else:
            print("[=] ip_default_ttl_hours already exists in users table")

        if "ia_default_ttl_hours" not in user_columns:
            conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN ia_default_ttl_hours INTEGER DEFAULT 24"
                )
            )
            print("[+] Added ia_default_ttl_hours to users table")
        else:
            print("[=] ia_default_ttl_hours already exists in users table")

        # Check if columns exist in ips table
        result = conn.execute(text("PRAGMA table_info(ips)"))
        ip_columns = [row[1] for row in result.fetchall()]

        if "expires_at" not in ip_columns:
            conn.execute(text("ALTER TABLE ips ADD COLUMN expires_at DATETIME"))
            print("[+] Added expires_at to ips table")
        else:
            print("[=] expires_at already exists in ips table")

        if "is_permanent" not in ip_columns:
            conn.execute(
                text("ALTER TABLE ips ADD COLUMN is_permanent INTEGER DEFAULT 0")
            )
            print("[+] Added is_permanent to ips table")
        else:
            print("[=] is_permanent already exists in ips table")

        # Check if columns exist in instantaccess table
        result = conn.execute(text("PRAGMA table_info(instantaccess)"))
        ia_columns = [row[1] for row in result.fetchall()]

        if "expires_at" not in ia_columns:
            conn.execute(
                text("ALTER TABLE instantaccess ADD COLUMN expires_at DATETIME")
            )
            print("[+] Added expires_at to instantaccess table")
        else:
            print("[=] expires_at already exists in instantaccess table")

        if "is_permanent" not in ia_columns:
            conn.execute(
                text(
                    "ALTER TABLE instantaccess ADD COLUMN is_permanent INTEGER DEFAULT 0"
                )
            )
            print("[+] Added is_permanent to instantaccess table")
        else:
            print("[=] is_permanent already exists in instantaccess table")

        conn.commit()

    print("[+] Migration complete!")


if __name__ == "__main__":
    try:
        migrate()
    except (SQLAlchemyError, ImportError) as e:
        print(f"[!] Migration failed: {e}")
        sys.exit(1)
