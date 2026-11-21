"""Issue #4: expiry is enforced at read time, independently of cleanup."""

from datetime import timedelta

import pytest

pytestmark = pytest.mark.characterization


@pytest.mark.parametrize("admin_visibility", [False, True])
@pytest.mark.parametrize("view", ["json", "html"])
def test_export_filters_expired_ips_without_waiting_for_cleanup(
    admin_visibility,
    view,
    app_modules,
    monkeypatch,
    db,
    user,
    admin,
    client,
    login,
    frozen_time,
):
    """Export omits expired rows while retaining active and permanent addresses."""
    monkeypatch.setattr(
        app_modules.settings.settings, "ADMIN_SEE_USERS_IP", admin_visibility
    )
    models = app_modules.models
    rows = [
        models.Ip(
            owner_id=user.id,
            value="198.51.100.31",
            expires_at=frozen_time - timedelta(seconds=1),
        ),
        models.Ip(
            owner_id=user.id,
            value="198.51.100.32",
            expires_at=frozen_time + timedelta(hours=1),
        ),
        models.Ip(
            owner_id=user.id, value="198.51.100.33", is_permanent=True, expires_at=None
        ),
        models.Ip(
            owner_id=admin.id, value="192.0.2.34", is_permanent=True, expires_at=None
        ),
    ]
    db.add_all(rows)
    db.commit()
    assert rows[0].expires_at < frozen_time < rows[1].expires_at
    assert rows[2].is_permanent and rows[2].expires_at is None
    login(client, admin if admin_visibility else user)
    before = _snapshot(db, models)
    response = client.get(
        "/ips/config/", headers={"Cli": "true"} if view == "json" else {}
    )
    assert response.status_code == 200
    if view == "json":
        payload = response.json()
        assert isinstance(payload, list)
        assert all(set(item) == {"owner", "value", "description"} for item in payload)
        values = {item["value"] for item in payload}
    else:
        assert response.template.name == "ips.html"
        values = {item.value for item in response.context["ips"]}
    assert {rows[1].value, rows[2].value} <= values
    assert (rows[3].value in values) is admin_visibility
    assert _snapshot(db, models) == before, (
        "Export must not rely on deleting expired rows"
    )
    assert rows[0].value not in values


def _snapshot(db, models):
    """Read persisted fields for every synthetic model, bypassing cached objects."""
    db.expire_all()
    return {
        model.__name__: [
            tuple(getattr(row, column.name) for column in model.__table__.columns)
            for row in db.query(model).order_by(model.id).all()
        ]
        for model in (models.User, models.Ip, models.InstantAccess, models.Token)
    }


@pytest.fixture
def expiry_rows(db, app_modules, user, admin, other_user, frozen_time):
    """Seed each owner with expired, boundary, future and timeless addresses."""
    rows = []
    allowed = {}
    for index, owner in enumerate((user, admin, other_user), start=1):
        allowed[owner.id] = set()
        states = [
            (False, frozen_time - timedelta(microseconds=1), False),
            (False, frozen_time, False),
            (False, frozen_time + timedelta(microseconds=1), True),
            (True, None, True),
            (True, frozen_time - timedelta(days=1), True),
            (False, None, True),
        ]
        for suffix, (permanent, expiration, visible) in enumerate(states, start=1):
            value = f"198.51.100.{index * 10 + suffix}"
            row = app_modules.models.Ip(
                owner_id=owner.id,
                value=value,
                description=f"synthetic-{value}",
                origin="synthetic",
                is_permanent=permanent,
                expires_at=expiration,
            )
            rows.append(row)
            if visible:
                allowed[owner.id].add(value)
    db.add_all(rows)
    db.commit()
    assert len(rows) == db.query(app_modules.models.Ip).count() == 18
    return rows, allowed


def _expected(actor, visibility, allowed):
    """Preserve the existing admin visibility rule without widening user access."""
    return (
        set().union(*allowed.values())
        if actor.is_admin and visibility
        else allowed[actor.id]
    )


@pytest.mark.parametrize("role", ["ordinary", "admin"])
@pytest.mark.parametrize("visibility", [False, True])
def test_crud_reads_filter_expiration_without_mutating(
    role,
    visibility,
    expiry_rows,
    user,
    admin,
    db,
    app_modules,
    monkeypatch,
):
    """Expiration equality is denied; permanence and absent TTL remain supported."""
    monkeypatch.setattr(app_modules.settings.settings, "ADMIN_SEE_USERS_IP", visibility)
    actor = admin if role == "admin" else user
    _, allowed = expiry_rows
    before = _snapshot(db, app_modules.models)
    actual = {row.value for row in app_modules.crud.get_ips(db, actor)}
    assert actual == _expected(actor, visibility, allowed)
    assert _snapshot(db, app_modules.models) == before


@pytest.mark.parametrize("role", ["ordinary", "admin"])
@pytest.mark.parametrize("visibility", [False, True])
@pytest.mark.parametrize("view", ["html", "json"])
@pytest.mark.parametrize("mode", ["cookie", "bearer"])
def test_http_reads_filter_expiration_without_cleanup(
    role,
    visibility,
    view,
    mode,
    expiry_rows,
    user,
    admin,
    other_user,
    db,
    app_modules,
    monkeypatch,
    client,
    login,
    password,
):
    """Both rendered HTML and unchanged JSON exports respect expiry and ownership."""
    monkeypatch.setattr(app_modules.settings.settings, "ADMIN_SEE_USERS_IP", visibility)
    actor = admin if role == "admin" else user
    rows, allowed = expiry_rows
    if mode == "cookie":
        login(client, actor)
    else:
        response = client.post(
            "/signin",
            data={
                "username": actor.email,
                "password": password,
                "scope": "cli",
            },
        )
        assert response.status_code == 200
        assert "access_token" not in client.cookies
        client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    before = _snapshot(db, app_modules.models)
    response = client.get(
        "/ips/config/", headers={"Cli": "true"} if view == "json" else {}
    )
    assert response.status_code == 200
    expected = _expected(actor, visibility, allowed)
    if view == "json":
        payload = response.json()
        assert all(set(item) == {"owner", "value", "description"} for item in payload)
        assert {item["value"] for item in payload} == expected
        emails = {account.id: account.email for account in (user, admin, other_user)}
        for item in payload:
            row = next(row for row in rows if row.value == item["value"])
            assert item["owner"] == emails[row.owner_id]
            assert item["description"] == row.description
    else:
        assert response.template.name == "ips.html"
        assert {row.value for row in response.context["ips"]} == expected
        for row in rows:
            assert (f"<code>{row.value}</code>" in response.text) is (
                row.value in expected
            )
    assert _snapshot(db, app_modules.models) == before


@pytest.mark.parametrize("role", ["ordinary", "admin"])
@pytest.mark.parametrize("form", [{}, {"action": "create", "ip": "invalid-address"}])
def test_post_rerenders_filter_expiration_without_mutating(
    role,
    form,
    expiry_rows,
    user,
    admin,
    db,
    app_modules,
    monkeypatch,
    client,
    login,
):
    """Normal and validation-error rerenders use the same filtered read query."""
    monkeypatch.setattr(app_modules.settings.settings, "ADMIN_SEE_USERS_IP", True)
    actor = admin if role == "admin" else user
    rows, allowed = expiry_rows
    login(client, actor)
    before = _snapshot(db, app_modules.models)
    response = client.post("/ips/config/", data=form)
    assert response.status_code == 200
    expected = _expected(actor, True, allowed)
    assert {row.value for row in response.context["ips"]} == expected
    for row in rows:
        assert (f"<code>{row.value}</code>" in response.text) is (row.value in expected)
    assert _snapshot(db, app_modules.models) == before
