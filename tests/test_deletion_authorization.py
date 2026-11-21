"""Owner-only deletion regressions for #2; global-admin rights are deferred to #30."""

import pytest

pytestmark = pytest.mark.characterization


def _snapshot(db, models):
    """Read persisted synthetic fields for every model, bypassing cached objects."""
    db.expire_all()
    return {
        model.__name__: [
            tuple(getattr(row, column.name) for column in model.__table__.columns)
            for row in db.query(model).order_by(model.id).all()
        ]
        for model in (models.User, models.Ip, models.InstantAccess, models.Token)
    }


def _seed(db, app_modules, account):
    """Create owned IP, link, associated IP and token without private configuration."""
    models, crud = app_modules.models, app_modules.crud
    ip = crud.create_user_ip(
        db, account.id, f"198.51.100.{account.id + 10}", ttl_hours=3
    )
    link = crud.create_instant_access(
        db, "https://example.com/", account.id, ttl_hours=3
    )
    linked = crud.create_user_ip(
        db,
        account.id,
        f"192.0.2.{account.id + 10}",
        origin=link.unique_link,
        ttl_hours=3,
    )
    token = models.Token(
        owner_id=account.id,
        key=f"synthetic-{account.id}",
        secret=account.hashed_password,
        description="synthetic token",
    )
    db.add(token)
    db.commit()
    return {"ip": ip.id, "link": link.id, "token": token.id, "linked_ip": linked.id}


def _delete_request(resource, actor, identifier):
    """Build the normal route/form for each deletion without changing actor identity."""
    return {
        "ip": ("/ips/config/", {"ip_id": identifier}),
        "link": ("/instant-access/config/", {"link_id": identifier}),
        "token": (f"/users/details/{actor.id}", {"token_id": identifier}),
    }[resource]


def _authenticate(client, account, mode, login, password):
    """Use the real web or CLI sign-in; never mock authentication."""
    if mode == "cookie":
        login(client, account)
    else:
        response = client.post(
            "/signin",
            data={
                "username": account.email,
                "password": password,
                "scope": "cli",
            },
        )
        assert response.status_code == 200
        assert "access_token" not in client.cookies
        client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"


@pytest.mark.parametrize("resource", ["ip", "link", "token"])
@pytest.mark.parametrize("role", ["ordinary", "admin"])
@pytest.mark.parametrize("mode", ["cookie", "bearer"])
def test_cross_owner_delete_is_denied_without_mutation(
    resource,
    role,
    mode,
    app_modules,
    db,
    user,
    other_user,
    admin,
    client,
    login,
    password,
    monkeypatch,
):
    """Visibility/admin status must not silently grant mutation rights before #30."""
    actor = admin if role == "admin" else user
    monkeypatch.setattr(app_modules.settings.settings, "ADMIN_SEE_USERS_IP", True)
    own = _seed(db, app_modules, actor)
    victim = _seed(db, app_modules, other_user)
    assert actor.id != other_user.id
    assert own[resource] != victim[resource]
    _authenticate(client, actor, mode, login, password)
    before = _snapshot(db, app_modules.models)
    path, fields = _delete_request(resource, actor, victim[resource])
    response = client.post(path, data={"action": "delete", **fields})
    after = _snapshot(db, app_modules.models)
    assert response.status_code == 404
    assert after == before
    assert other_user.email not in response.text


def test_deleting_owned_link_preserves_other_owner_ip_with_same_origin(
    client,
    login,
    user,
    other_user,
    db,
    app_modules,
):
    """An origin string alone must not authorize deletion across ownership boundaries."""
    own = _seed(db, app_modules, user)
    link = db.get(app_modules.models.InstantAccess, own["link"])
    foreign = app_modules.crud.create_user_ip(
        db, other_user.id, "203.0.113.20", origin=link.unique_link, ttl_hours=3
    )
    foreign_id = foreign.id
    login(client, user)
    before = _snapshot(db, app_modules.models)
    response = client.post(
        "/instant-access/config/", data={"action": "delete", "link_id": link.id}
    )
    after = _snapshot(db, app_modules.models)
    assert response.status_code == 200
    assert db.get(app_modules.models.Ip, foreign_id) is not None
    expected = dict(before)
    expected["InstantAccess"] = [
        row for row in before["InstantAccess"] if row[0] != own["link"]
    ]
    expected["Ip"] = [row for row in before["Ip"] if row[0] != own["linked_ip"]]
    assert after == expected


@pytest.mark.parametrize("resource", ["ip", "link", "token"])
@pytest.mark.parametrize("role", ["ordinary", "admin"])
@pytest.mark.parametrize("mode", ["cookie", "bearer"])
def test_owner_can_delete_only_the_requested_resource(
    resource,
    role,
    mode,
    app_modules,
    db,
    user,
    other_user,
    admin,
    client,
    login,
    password,
):
    """Valid deletions preserve accounts, other resources, and token-owner TOTP."""
    actor = admin if role == "admin" else user
    own = _seed(db, app_modules, actor)
    _seed(db, app_modules, other_user)
    _authenticate(client, actor, mode, login, password)
    actor.twofactor = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    db.commit()
    before = _snapshot(db, app_modules.models)
    path, fields = _delete_request(resource, actor, own[resource])
    response = client.post(path, data={"action": "delete", **fields})
    after = _snapshot(db, app_modules.models)
    assert response.status_code == 200
    expected = dict(before)
    model_name = {"ip": "Ip", "link": "InstantAccess", "token": "Token"}[resource]
    expected[model_name] = [
        row for row in before[model_name] if row[0] != own[resource]
    ]
    if resource == "link":
        expected["Ip"] = [row for row in before["Ip"] if row[0] != own["linked_ip"]]
    assert after == expected


@pytest.mark.parametrize("resource", ["ip", "link", "token"])
@pytest.mark.parametrize("identifier", ["12345", "not-an-id", ""])
def test_missing_or_invalid_resource_returns_same_404_without_mutation(
    resource,
    identifier,
    app_modules,
    db,
    user,
    client,
    login,
):
    """Missing and foreign resources share one non-disclosing response."""
    _seed(db, app_modules, user)
    login(client, user)
    before = _snapshot(db, app_modules.models)
    path, fields = _delete_request(resource, user, identifier)
    response = client.post(path, data={"action": "delete", **fields})
    assert response.status_code == 404
    assert response.json() == {"detail": "Resource not found"}
    assert _snapshot(db, app_modules.models) == before


@pytest.mark.parametrize("resource", ["ip", "link", "token"])
def test_crud_rejects_other_owner_without_mutation(
    resource, app_modules, db, user, other_user
):
    """Ownership is enforced by CRUD as well as HTTP routes."""
    victim = _seed(db, app_modules, other_user)
    before = _snapshot(db, app_modules.models)
    removed = getattr(app_modules.crud, f"delete_{resource}")(
        db, victim[resource], owner_id=user.id
    )
    assert removed is False
    assert _snapshot(db, app_modules.models) == before


@pytest.mark.parametrize("resource", ["ip", "link", "token"])
def test_crud_requires_explicit_owner(resource, app_modules, db, user):
    """A future caller cannot accidentally use an unscoped deletion API."""
    own = _seed(db, app_modules, user)
    before = _snapshot(db, app_modules.models)
    with pytest.raises(TypeError, match="owner_id"):
        getattr(app_modules.crud, f"delete_{resource}")(db, own[resource])
    assert _snapshot(db, app_modules.models) == before


@pytest.mark.parametrize("identifier", ["own", "victim", "missing"])
def test_admin_cannot_delete_tokens_through_another_account_page(
    identifier,
    app_modules,
    db,
    user,
    admin,
    client,
    login,
):
    """The selected target page must not be used as deletion authority before #30."""
    own = _seed(db, app_modules, admin)
    victim = _seed(db, app_modules, user)
    login(client, admin)
    before = _snapshot(db, app_modules.models)
    token_id = {"own": own["token"], "victim": victim["token"], "missing": 12345}[
        identifier
    ]
    response = client.post(
        f"/users/details/{user.id}", data={"action": "delete", "token_id": token_id}
    )
    assert response.status_code == 404
    assert _snapshot(db, app_modules.models) == before


@pytest.mark.parametrize("role", ["ordinary", "admin"])
def test_forbidden_token_delete_stops_all_other_submitted_changes(
    role,
    app_modules,
    db,
    user,
    other_user,
    admin,
    client,
    login,
):
    """A refused deletion must not generate tokens, update TTLs or disable TOTP."""
    actor = admin if role == "admin" else user
    _seed(db, app_modules, actor)
    victim = _seed(db, app_modules, other_user)
    login(client, actor)
    actor.twofactor = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    db.commit()
    before = _snapshot(db, app_modules.models)
    response = client.post(
        f"/users/details/{actor.id}",
        data={
            "action": "delete",
            "token_id": victim["token"],
            "token": "true",
            "ip_default_ttl_hours": "6",
            "ia_default_ttl_hours": "48",
        },
    )
    assert response.status_code == 404
    assert _snapshot(db, app_modules.models) == before


@pytest.mark.parametrize("resource", ["ip", "link", "token"])
def test_anonymous_delete_is_denied_without_mutation(
    resource, app_modules, db, user, client
):
    """The deletion routes continue to require real authentication."""
    own = _seed(db, app_modules, user)
    before = _snapshot(db, app_modules.models)
    path, fields = _delete_request(resource, user, own[resource])
    response = client.post(path, data={"action": "delete", **fields})
    assert response.status_code == 401
    assert _snapshot(db, app_modules.models) == before
