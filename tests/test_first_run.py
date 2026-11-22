"""First-run setup uses a new SQLite file and permits exactly one initial administrator."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

SETUP_ORIGIN = {"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"}


@pytest.fixture
def setup_instance(app_modules, client_factory, tmp_path, monkeypatch):
    from database import get_db, initialize_database

    path = tmp_path / "first-run.sqlite3"
    engine = create_engine(f"sqlite:///{path}")
    factory = sessionmaker(bind=engine)
    settings = app_modules.settings.settings
    monkeypatch.setattr(settings, "DISABLE_REGISTER", True)

    def request_session():
        with factory() as session:
            yield session

    app_modules.main.app.dependency_overrides[get_db] = request_session
    try:
        assert not path.exists()
        initialize_database(engine)
        assert path.is_file() and inspect(engine).has_table("users")
        yield client_factory, factory, engine
    finally:
        engine.dispose()


def test_new_database_offers_setup_and_survives_restart(setup_instance):
    from database import initialize_database

    clients, _, engine = setup_instance
    initialize_database(engine)
    client = clients()
    response = client.get("/")
    assert response.status_code == 303
    assert response.headers["location"] == "/setup"
    form = client.get("/setup")
    assert form.status_code == 200
    assert 'name="setup_token"' not in form.text
    assert form.headers["cache-control"] == "no-store"
    assert form.headers["referrer-policy"] == "same-origin"


def test_setup_rejects_invalid_credentials(setup_instance, app_modules, password):
    clients, factory, _ = setup_instance
    client = clients()
    fields = {
        "email": "admin@example.com",
        "password": password,
        "confirm_password": password,
    }
    for overrides, status in (
        ({"email": "not-an-email"}, 422),
        ({"password": "weak", "confirm_password": "weak"}, 422),
        ({"confirm_password": "wrong"}, 422),
    ):
        data = {**fields, **overrides}
        response = client.post("/setup", data=data, headers=SETUP_ORIGIN)
        assert response.status_code == status
        assert response.headers["cache-control"] == "no-store"
        assert password not in response.text
    with factory() as db:
        assert db.query(app_modules.models.User).count() == 0


def test_setup_creates_one_admin_without_token_and_permanently_closes(
    setup_instance, app_modules, password
):
    from database import initialize_database

    clients, factory, engine = setup_instance
    client = clients()
    data = {
        "email": "first-admin@example.com",
        "password": password,
        "confirm_password": password,
    }
    response = client.post(
        "/setup",
        data=data,
        headers=SETUP_ORIGIN,
    )
    assert response.status_code == 303 and response.headers["location"] == "/signin"
    assert client.post("/setup", data=data).status_code == 404
    login = client.post(
        "/signin", data={"username": data["email"], "password": password}
    )
    assert login.status_code == 200 and "access_token" in client.cookies
    assert client.get("/docs").status_code == 200
    user = app_modules.models.User
    with factory() as db:
        admin = db.query(user).one()
        assert admin.is_admin and admin.is_active
        assert admin.hashed_password != password
        db.delete(admin)
        db.commit()
    initialize_database(engine)
    assert clients().get("/").status_code == 200
    assert clients().get("/setup").status_code == 404


def test_concurrent_posts_create_at_most_one_admin(
    setup_instance, app_modules, password
):
    clients, factory, _ = setup_instance
    barrier = Barrier(2, timeout=10)
    first, second = clients(), clients()

    def submit(client, email):
        barrier.wait()
        return client.post(
            "/setup",
            headers=SETUP_ORIGIN,
            data={
                "email": email,
                "password": password,
                "confirm_password": password,
            },
        ).status_code

    with ThreadPoolExecutor(2) as workers:
        results = [
            workers.submit(submit, client, f"admin{i}@example.com")
            for i, client in enumerate((first, second))
        ]
        assert sorted(result.result(timeout=15) for result in results) == [303, 404]
    with factory() as db:
        assert db.query(app_modules.models.User).filter_by(is_admin=True).count() == 1


def test_existing_sqlite_is_not_enrolled(app_modules, client, tmp_path, monkeypatch):
    from database import get_db, initialize_database

    path = tmp_path / "existing.sqlite3"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE legacy (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO legacy VALUES (42)")
    settings = app_modules.settings.settings
    monkeypatch.setattr(settings, "DISABLE_REGISTER", True)
    factory = sessionmaker(bind=engine)

    def request_session():
        with factory() as session:
            yield session

    app_modules.main.app.dependency_overrides[get_db] = request_session
    try:
        initialize_database(engine)
        assert client.get("/").status_code == 200
        assert client.get("/setup").status_code == 404
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql("SELECT id FROM legacy").scalar_one() == 42
            )
    finally:
        engine.dispose()


def test_setup_is_unavailable_with_registration_open(
    setup_instance, app_modules, monkeypatch
):
    clients, _, _ = setup_instance
    monkeypatch.setattr(app_modules.settings.settings, "DISABLE_REGISTER", False)
    client = clients()
    assert client.get("/").status_code == 200
    assert client.get("/setup").status_code == 404
    assert client.post("/setup").status_code == 404


def test_cli_account_creation_closes_web_setup(
    setup_instance, app_modules, password, monkeypatch
):
    from importlib import import_module

    clients, factory, engine = setup_instance
    cli = import_module("init_admin")
    monkeypatch.setattr(cli, "engine", engine)
    monkeypatch.setattr(cli, "SessionLocal", factory)
    assert cli.main(["cli-admin@example.com", password]) == 0
    with factory() as db:
        admin = db.query(app_modules.models.User).one()
        assert admin.is_admin
        db.delete(admin)
        db.commit()
    assert clients().get("/setup").status_code == 404


@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
        {"Origin": "https://other.example"},
        {},
    ],
)
def test_setup_rejects_cross_origin_browser_posts(setup_instance, password, headers):
    clients, _, _ = setup_instance
    response = clients().post(
        "/setup",
        headers=headers,
        data={
            "email": "admin@example.com",
            "password": password,
            "confirm_password": password,
        },
    )
    assert response.status_code == 403


def test_setup_rejects_unconfigured_host(setup_instance, password):
    clients, _, _ = setup_instance
    client = clients(base_url="http://other.example")
    assert client.get("/setup").status_code == 403
    response = client.post(
        "/setup",
        headers={"Origin": "http://other.example", "Sec-Fetch-Site": "same-origin"},
        data={
            "email": "admin@example.com",
            "password": password,
            "confirm_password": password,
        },
    )
    assert response.status_code == 403


@pytest.mark.parametrize("uri", [False, True])
def test_schema_creation_enrolls_uninitialized_file_once(app_modules, tmp_path, uri):
    from database import initialize_database

    path = tmp_path / "initialization.sqlite3"
    url = f"sqlite:///file:{path}?mode=rwc&uri=true" if uri else f"sqlite:///{path}"
    engine = create_engine(url)
    try:
        # One process can have opened SQLite before either initializer obtains the lock.
        with engine.connect():
            assert path.exists()
        with ThreadPoolExecutor(2) as workers:
            list(workers.map(initialize_database, (engine, engine)))
        with sessionmaker(bind=engine)() as db:
            assert db.query(app_modules.models.InitialSetup).count() == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("exclusive", [False, True])
def test_setup_writer_lock_returns_retryable_error(
    setup_instance, app_modules, password, exclusive
):
    from sqlalchemy import event

    clients, factory, engine = setup_instance

    @event.listens_for(engine, "checkout")
    def no_busy_wait(connection, *_):
        connection.execute("PRAGMA busy_timeout=0")

    client = clients(raise_server_exceptions=False)
    with engine.connect() as writer:
        writer.exec_driver_sql("BEGIN EXCLUSIVE" if exclusive else "BEGIN IMMEDIATE")
        if exclusive:
            for path in ("/", "/setup"):
                blocked = client.get(path)
                assert blocked.status_code == 503
                assert blocked.headers["retry-after"] == "1"
        response = client.post(
            "/setup",
            headers=SETUP_ORIGIN,
            data={
                "email": "admin@example.com",
                "password": password,
                "confirm_password": password,
            },
        )
        assert response.status_code == 503
        assert response.headers["retry-after"] == "1"
        assert response.headers["cache-control"] == "no-store"
    with factory() as db:
        assert db.query(app_modules.models.User).count() == 0
