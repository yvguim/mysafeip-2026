"""Isolated application imports, real authentication and disposable SQLite fixtures."""

import importlib
import secrets
import shutil
import socket
import sqlite3
import sys
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "Test-only-42!"
APP_MODULE_NAMES = (
    "settings",
    "database",
    "models",
    "schemas",
    "security",
    "auth",
    "crud",
    "ttl",
    "main",
)


def _forbidden_network(*args, **kwargs):
    raise RuntimeError("External network is forbidden in application tests")


@pytest.fixture(scope="session")
def app_modules(tmp_path_factory):
    """Import only allowlisted sources in a temporary cwd with explicit test settings."""
    from apscheduler.schedulers.background import BackgroundScheduler

    runtime = tmp_path_factory.mktemp("mysafeip-runtime")
    source = ROOT / "app"
    # Only import Python source from app/. Never copy/open legacy dotenv files or databases.
    # Keep original source paths so coverage measures the actual application, including unrun modules.
    for name in ("templates", "languages"):
        shutil.copytree(source / name, runtime / name)

    environment = {
        "PYTHON_DOTENV_DISABLED": "1",
        "JWT_SECRET": secrets.token_hex(48),
        "SETUP_TOKEN": "",
        "ALGORITHM": "HS256",
        "ACCESS_TOKEN_EXPIRE_MINUTES": "30",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{runtime / 'bootstrap.sqlite3'}",
        "URL_WEBSITE": "http://testserver",
        "DEFAULT_LANGUAGE": "en",
        "DISABLE_REGISTER": "false",
        "ADMIN_SEE_USERS_IP": "false",
        "TRUSTED_PROXIES": "false",
    }
    import dotenv

    original_connect = sqlite3.dbapi2.connect

    def temporary_connect(database, *args, **kwargs):
        filename = database
        if kwargs.get("uri") and str(database).startswith("file:"):
            uri = urlsplit(database)
            if uri.netloc:
                raise RuntimeError("Remote SQLite URIs are forbidden in tests")
            filename = unquote(uri.path)
        if not Path(filename).resolve().is_relative_to(runtime.parent):
            raise RuntimeError(
                "SQLite connections must stay in this pytest temporary directory"
            )
        return original_connect(database, *args, **kwargs)

    def forbidden_dotenv_search(*args, **kwargs):
        raise RuntimeError("Dotenv discovery is forbidden in application tests")

    with pytest.MonkeyPatch.context() as scoped:
        scoped.setattr(socket, "create_connection", _forbidden_network)
        scoped.setattr(socket.socket, "connect", _forbidden_network)
        scoped.setattr(socket.socket, "connect_ex", _forbidden_network)
        scoped.setattr(sys, "dont_write_bytecode", True)
        scoped.setattr(sqlite3, "connect", temporary_connect)
        scoped.setattr(sqlite3.dbapi2, "connect", temporary_connect)
        scoped.setattr(dotenv, "find_dotenv", forbidden_dotenv_search)
        for name, value in environment.items():
            scoped.setenv(name, value)
        scoped.chdir(runtime)
        scoped.syspath_prepend(str(source))
        for name in APP_MODULE_NAMES:
            if name in sys.modules:
                raise RuntimeError(
                    f"Application module imported before isolation: {name}"
                )
        with (
            patch.object(BackgroundScheduler, "start"),
            patch.object(BackgroundScheduler, "shutdown"),
        ):
            modules = {name: importlib.import_module(name) for name in APP_MODULE_NAMES}
            modules["instant_router"] = importlib.import_module(
                "routers.instant_access"
            )
            modules["runtime"] = runtime
            try:
                yield SimpleNamespace(**modules)
            finally:
                modules["database"].engine.dispose()
                for name in (
                    *APP_MODULE_NAMES,
                    "init_admin",
                    "routers",
                    "routers.auth",
                    "routers.ips",
                    "routers.setup",
                    "routers.users",
                    "routers.instant_access",
                ):
                    sys.modules.pop(name, None)


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    """Fail if tests try to connect out; TestClient uses an in-process ASGI transport."""
    monkeypatch.setattr(socket, "create_connection", _forbidden_network)
    monkeypatch.setattr(socket.socket, "connect", _forbidden_network)
    monkeypatch.setattr(socket.socket, "connect_ex", _forbidden_network)


@pytest.fixture
def db(app_modules, tmp_path, monkeypatch):
    """Give each test a separate file, engine and request sessions; close all on exit."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    uri = f"sqlite:///{tmp_path / 'application.sqlite3'}"
    engine = create_engine(uri, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    app_modules.models.Base.metadata.create_all(engine)
    monkeypatch.setattr(app_modules.database, "engine", engine)
    monkeypatch.setattr(app_modules.database, "SessionLocal", factory)
    monkeypatch.setattr(app_modules.main, "engine", engine)
    monkeypatch.setattr(app_modules.main, "SessionLocal", factory)
    monkeypatch.setattr(app_modules.settings.settings, "SQLALCHEMY_DATABASE_URI", uri)

    def override_db():
        with factory() as request_session:
            yield request_session

    application = app_modules.main.app
    application.dependency_overrides[app_modules.database.get_db] = override_db
    try:
        with factory() as session:
            yield session
    finally:
        application.dependency_overrides.clear()
        engine.dispose()


@pytest.fixture(scope="session")
def password():
    """Return a public synthetic password, never an existing credential."""
    return PASSWORD


@pytest.fixture(scope="session")
def password_hash(app_modules, password):
    """Cache one real bcrypt hash for fast seed creation, without mocking bcrypt."""
    return app_modules.security.get_password_hash(password)


@pytest.fixture
def user_factory(db, app_modules, password_hash):
    """Create synthetic users; real CRUD/hash behavior is covered separately."""

    def create(email=None, **attributes):
        email = (
            email or f"person{db.query(app_modules.models.User).count()}@example.com"
        )
        user = app_modules.models.User(
            email=email, hashed_password=password_hash, **attributes
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    return create


@pytest.fixture
def user(user_factory):
    """Create a normal active owner."""
    return user_factory("alice@example.com")


@pytest.fixture
def other_user(user_factory):
    """Create another normal active owner."""
    return user_factory("bob@example.com")


@pytest.fixture
def admin(user_factory):
    """Create an administrator, without using an existing account."""
    return user_factory("admin@example.com", is_admin=True)


@pytest.fixture
def client_factory(app_modules, db):
    """Create independent cookie jars, with real lifespan and no followed redirects."""
    from fastapi.testclient import TestClient

    with ExitStack() as stack:

        def create(**kwargs):
            kwargs.setdefault("follow_redirects", False)
            kwargs.setdefault("client", ("192.0.2.10", 50000))
            return stack.enter_context(TestClient(app_modules.main.app, **kwargs))

        yield create


@pytest.fixture
def client(client_factory):
    """Return an anonymous in-process HTTP client."""
    return client_factory()


@pytest.fixture
def login(password):
    """Authenticate a selected synthetic user using the real sign-in endpoint."""

    def authenticate(client, user, **extra):
        response = client.post(
            "/signin", data={"username": user.email, "password": password, **extra}
        )
        assert response.status_code == 200
        assert "access_token" in client.cookies, (
            "Expected successful real cookie authentication"
        )
        return response

    return authenticate


@pytest.fixture
def totp_time(monkeypatch):
    """Freeze PyOTP alone, without changing the shared datetime module or JWT clock."""
    import pyotp

    class TotpClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant if tz is None else instant.astimezone(tz)

    instant = TotpClock(2025, 1, 2, 12, 0, 0)
    if hasattr(pyotp.totp, "time"):
        # Newer PyOTP versions read a Unix timestamp via their local module reference.
        monkeypatch.setattr(pyotp.totp, "time", SimpleNamespace(time=instant.timestamp))
    else:
        monkeypatch.setattr(pyotp.totp, "datetime", SimpleNamespace(datetime=TotpClock))
    return instant


@pytest.fixture
def frozen_time(app_modules, monkeypatch):
    """Freeze business TTL clocks, leaving JWT wall-clock validation untouched."""
    instant = datetime.now().replace(microsecond=0)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return instant
            return instant.astimezone(tz)

    monkeypatch.setattr(app_modules.crud, "datetime", FrozenDateTime)
    monkeypatch.setattr(app_modules.instant_router, "datetime", FrozenDateTime)
    return instant
