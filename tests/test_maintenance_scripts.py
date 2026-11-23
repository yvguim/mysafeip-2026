"""Maintenance commands against disposable SQLite databases only."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Pytest's process-local guards do not carry over into script subprocesses.
ISOLATED_ENTRYPOINT = """
import runpy
import socket
import sqlite3
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import dotenv

app_dir, script, *args = sys.argv[1:]
temporary_root = Path.cwd().resolve()
connect = sqlite3.dbapi2.connect


def forbidden_network(*args, **kwargs):
    raise RuntimeError("External network is forbidden in maintenance tests")


def forbidden_dotenv(*args, **kwargs):
    raise RuntimeError("Dotenv discovery is forbidden in maintenance tests")


def temporary_connect(database, *args, **kwargs):
    filename = database
    if kwargs.get("uri") and str(database).startswith("file:"):
        uri = urlsplit(database)
        if uri.netloc:
            raise RuntimeError("Remote SQLite URIs are forbidden in maintenance tests")
        filename = unquote(uri.path)
    if not Path(filename).resolve().is_relative_to(temporary_root):
        raise RuntimeError("SQLite connections must stay in the maintenance test directory")
    return connect(database, *args, **kwargs)


socket.create_connection = socket.socket.connect = socket.socket.connect_ex = forbidden_network
sqlite3.connect = sqlite3.dbapi2.connect = temporary_connect
dotenv.find_dotenv = forbidden_dotenv
sys.path.insert(0, app_dir)
sys.argv = [script, *args]
runpy.run_path(script, run_name="__main__")
"""


def run_script(app_modules, tmp_path, database, script, *args, uri=False):
    database_url = (
        f"sqlite:///file:{quote(str(database))}?mode=rwc&uri=true"
        if uri
        else f"sqlite:///{database}"
    )
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
            "SQLALCHEMY_DATABASE_URI": database_url,
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


@pytest.mark.parametrize("uri", [False, True])
def test_reset_admin_recovers_login_without_totp(
    app_modules,
    tmp_path,
    db,
    user_factory,
    client_factory,
    login,
    password,
    totp_time,
    uri,
):
    import pyotp

    totp = pyotp.TOTP(pyotp.random_base32())
    admin = user_factory(
        "-ops$literal@example.org", is_admin=True, twofactor=totp.secret
    )
    email = admin.email
    login(client_factory(), admin, two_factor_code=totp.at(totp_time))

    result = run_script(
        app_modules,
        tmp_path,
        db.bind.url.database,
        "scripts/reset_admin.py",
        "--clear-totp",
        "--",
        email,
        uri=uri,
    )
    assert result.returncode == 0, result.stderr
    (new_password,) = result.stdout.splitlines()
    assert new_password != password
    assert app_modules.auth.password_validity(new_password)
    assert new_password not in result.stderr

    db.refresh(admin)
    assert admin.is_active and admin.is_admin
    assert admin.twofactor == ""
    assert admin.hashed_password != new_password
    assert app_modules.security.verify_password(new_password, admin.hashed_password)

    client = client_factory()
    client.post("/signin", data={"username": email, "password": password})
    assert "access_token" not in client.cookies
    client.post("/signin", data={"username": email, "password": new_password})
    assert "access_token" in client.cookies


def test_reset_admin_resets_regular_account_without_disabling_totp(
    app_modules,
    tmp_path,
    db,
    admin,
    user_factory,
    client_factory,
    login,
    password,
    totp_time,
):
    import pyotp

    totp = pyotp.TOTP(pyotp.random_base32())
    user = user_factory("-ops'$literal@example.org", twofactor=totp.secret)
    login(client_factory(), user, two_factor_code=totp.at(totp_time))
    admin_hash = admin.hashed_password

    result = run_script(
        app_modules,
        tmp_path,
        db.bind.url.database,
        "scripts/reset_admin.py",
        "--",
        user.email,
    )
    assert result.returncode == 0, result.stderr
    (new_password,) = result.stdout.splitlines()
    assert new_password != password
    db.refresh(user)
    db.refresh(admin)
    assert user.is_active and not user.is_admin
    assert user.twofactor == totp.secret
    assert admin.hashed_password == admin_hash

    def can_sign_in(candidate, code=""):
        client = client_factory()
        client.post(
            "/signin",
            data={
                "username": user.email,
                "password": candidate,
                "two_factor_code": code,
            },
        )
        return "access_token" in client.cookies

    assert not can_sign_in(password, totp.at(totp_time))
    assert not can_sign_in(new_password)
    assert can_sign_in(new_password, totp.at(totp_time))


def test_reset_admin_leaves_ineligible_accounts_untouched(
    app_modules, tmp_path, db, admin, user_factory
):
    inactive_admin = user_factory(is_admin=True, is_active=False)
    inactive_user = user_factory(is_active=False)
    database = db.bind.url.database
    with sqlite3.connect(database) as connection:
        before = connection.execute("SELECT * FROM users ORDER BY id").fetchall()

    for email in (inactive_admin.email, inactive_user.email, "missing@example.org"):
        result = run_script(
            app_modules, tmp_path, database, "scripts/reset_admin.py", email
        )
        assert result.returncode == 1
        assert result.stdout == ""
        assert "No active account" in result.stderr

    with sqlite3.connect(database) as connection:
        assert (
            connection.execute("SELECT * FROM users ORDER BY id").fetchall() == before
        )


@pytest.mark.parametrize("uri", [False, True])
def test_reset_admin_does_not_create_a_missing_database(app_modules, tmp_path, uri):
    database = tmp_path / "missing database.sqlite3"
    result = run_script(
        app_modules,
        tmp_path,
        database,
        "scripts/reset_admin.py",
        "admin@example.org",
        uri=uri,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "database not found" in result.stderr
    assert not database.exists()


def test_reset_admin_does_not_print_password_when_database_write_fails(
    app_modules, tmp_path, db, admin
):
    database = db.bind.url.database
    with sqlite3.connect(database) as connection:
        connection.executescript(
            "CREATE TRIGGER prevent_reset BEFORE UPDATE ON users "
            "BEGIN SELECT RAISE(ABORT, 'writes disabled'); END;"
        )
    result = run_script(
        app_modules, tmp_path, database, "scripts/reset_admin.py", admin.email
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "Unable to reset" in result.stderr
    assert "Traceback" not in result.stderr


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
