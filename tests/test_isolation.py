"""Safety properties of the test harness itself."""

import socket
import sqlite3
from pathlib import Path

import pytest

pytestmark = pytest.mark.characterization


def test_bootstrap_runs_outside_the_repository(app_modules):
    """Import side effects create only a temporary bootstrap database."""
    assert Path.cwd() == app_modules.runtime
    assert app_modules.runtime not in Path(__file__).resolve().parents
    assert not (app_modules.runtime / ".env").exists()
    assert not (app_modules.runtime / "sql_app.db").exists()
    assert not (app_modules.runtime / "test.db").exists()
    assert (
        Path(app_modules.main.__file__).parent
        == Path(__file__).resolve().parents[1] / "app"
    )
    assert app_modules.main.scheduler.running is False
    assert len(app_modules.main.scheduler.get_jobs()) == 2


def test_each_database_starts_empty(app_modules, db, tmp_path):
    """Every seedable table starts empty in a per-test SQLite file."""
    for model in (
        app_modules.models.User,
        app_modules.models.Ip,
        app_modules.models.InstantAccess,
        app_modules.models.Token,
    ):
        assert db.query(model).count() == 0
    assert Path(db.bind.url.database).parent == tmp_path
    assert app_modules.main.SessionLocal.kw["bind"] is db.bind


def test_outbound_connections_are_blocked():
    """A wrong URL must fail rather than reach the LAN or another service."""
    with pytest.raises(RuntimeError, match="External network is forbidden"):
        socket.create_connection(("192.0.2.1", 8000))


def test_repository_database_access_is_blocked(app_modules):
    """Reject repository paths before SQLite can open or create a file."""
    forbidden = Path(__file__).resolve().parents[1] / "app" / "never-open.sqlite3"
    with pytest.raises(RuntimeError, match="SQLite connections must stay"):
        sqlite3.connect(forbidden)
    assert not forbidden.exists()


def test_dotenv_discovery_is_blocked(app_modules):
    """Settings cannot search for an existing private dotenv file."""
    import dotenv

    with pytest.raises(RuntimeError, match="Dotenv discovery is forbidden"):
        dotenv.find_dotenv()


def test_public_home_works_in_process(client):
    """The real application can render templates without network access."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.template.name == "home.html"
