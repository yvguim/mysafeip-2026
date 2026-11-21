"""Maintenance commands against disposable SQLite databases only."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Pytest's process-local guards do not carry over into script subprocesses.
ISOLATED_ENTRYPOINT = """
import runpy
import socket
import sqlite3
import sys
from pathlib import Path

import dotenv

app_dir, script, *args = sys.argv[1:]
temporary_root = Path.cwd().resolve()
connect = sqlite3.dbapi2.connect


def forbidden_network(*args, **kwargs):
    raise RuntimeError("External network is forbidden in maintenance tests")


def forbidden_dotenv(*args, **kwargs):
    raise RuntimeError("Dotenv discovery is forbidden in maintenance tests")


def temporary_connect(database, *args, **kwargs):
    if not Path(database).resolve().is_relative_to(temporary_root):
        raise RuntimeError("SQLite connections must stay in the maintenance test directory")
    return connect(database, *args, **kwargs)


socket.create_connection = socket.socket.connect = socket.socket.connect_ex = forbidden_network
sqlite3.connect = sqlite3.dbapi2.connect = temporary_connect
dotenv.find_dotenv = forbidden_dotenv
sys.path.insert(0, app_dir)
sys.argv = [script, *args]
runpy.run_path(script, run_name="__main__")
"""


def run_script(app_modules, tmp_path, database, script, *args):
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            ISOLATED_ENTRYPOINT,
            str(ROOT / "app"),
            str(ROOT / script),
            *args,
        ],
        cwd=tmp_path,
        env={
            "PYTHON_DOTENV_DISABLED": "1",
            **{
                key: os.environ[key]
                for key in (
                    "JWT_SECRET",
                    "ALGORITHM",
                    "ACCESS_TOKEN_EXPIRE_MINUTES",
                    "URL_WEBSITE",
                    "DEFAULT_LANGUAGE",
                    "DISABLE_REGISTER",
                    "ADMIN_SEE_USERS_IP",
                    "TRUSTED_PROXIES",
                )
            },
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database}",
        },
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def test_init_admin_usage_without_traceback(app_modules, tmp_path):
    database = tmp_path / "unused.sqlite3"
    result = run_script(app_modules, tmp_path, database, "app/init_admin.py")
    assert result.returncode == 2
    assert "Usage:" in result.stderr
    assert "Traceback" not in result.stderr
    assert not database.exists()


def test_init_admin_preserves_existing_account_on_duplicate(app_modules, tmp_path):
    database = tmp_path / "admin.sqlite3"
    engine = app_modules.database.create_engine(f"sqlite:///{database}")
    try:
        app_modules.models.Base.metadata.create_all(engine)
    finally:
        engine.dispose()
    args = ("operator@example.org", "Synthetic-42!")
    first = run_script(app_modules, tmp_path, database, "app/init_admin.py", *args)
    assert first.returncode == 0, first.stderr
    duplicate = run_script(app_modules, tmp_path, database, "app/init_admin.py", *args)
    assert duplicate.returncode == 1
    assert "Email already registered" in duplicate.stderr
    assert "Traceback" not in duplicate.stderr
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT email, is_admin, is_active FROM users"
        ).fetchall() == [(args[0], 1, 1)]


def test_migrate_legacy_database_is_idempotent(app_modules, tmp_path):
    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            "CREATE TABLE users (id INTEGER PRIMARY KEY); INSERT INTO users VALUES (1);"
            "CREATE TABLE ips (id INTEGER PRIMARY KEY); INSERT INTO ips VALUES (2);"
            "CREATE TABLE instantaccess (id INTEGER PRIMARY KEY); INSERT INTO instantaccess VALUES (3);"
        )
    for _ in range(2):
        result = run_script(app_modules, tmp_path, database, "migrate.py")
        assert result.returncode == 0, result.stdout + result.stderr
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT * FROM users").fetchall() == [(1, 1, 24)]
        assert connection.execute("SELECT * FROM ips").fetchall() == [(2, None, 0)]
        assert connection.execute("SELECT * FROM instantaccess").fetchall() == [
            (3, None, 0)
        ]


def test_migrate_reports_missing_tables(app_modules, tmp_path):
    result = run_script(app_modules, tmp_path, tmp_path / "empty.sqlite3", "migrate.py")
    assert result.returncode == 1
    assert "Migration failed:" in result.stdout
    assert "Traceback" not in result.stderr
