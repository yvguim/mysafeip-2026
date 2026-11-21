"""Inactive-account refusals for #3, without changing the historical HTTP contract."""

from html import unescape
from http.cookies import SimpleCookie

import pytest

pytestmark = pytest.mark.characterization


def _snapshot(db, models):
    """Read persisted synthetic rows rather than trusting SQLAlchemy's identity map."""
    db.expire_all()
    return {
        model.__name__: [
            tuple(getattr(row, column.name) for column in model.__table__.columns)
            for row in db.query(model).order_by(model.id).all()
        ]
        for model in (models.User, models.Ip, models.InstantAccess, models.Token)
    }


@pytest.mark.parametrize("channel", ["web", "cli"])
@pytest.mark.parametrize("role", ["ordinary", "admin"])
@pytest.mark.parametrize("language", ["fr", "en"])
def test_inactive_password_login_is_denied(
    channel,
    role,
    language,
    client,
    db,
    user,
    other_user,
    admin,
    password,
    app_modules,
):
    """A correct password must not grant a session to an inactive account of either role."""
    account = admin if role == "admin" else user
    account.is_active = False
    db.commit()
    before = _snapshot(db, app_modules.models)
    assert account.is_active is False
    client.cookies.set("lang", language)
    response = client.post(
        "/signin",
        data={
            "username": account.email,
            "password": password,
            **({"scope": "cli"} if channel == "cli" else {}),
        },
    )
    assert response.status_code == 200
    issued_cookie = "access_token" in client.cookies
    issued_json = (
        bool(response.json().get("access_token"))
        if response.headers.get("content-type", "").startswith("application/json")
        else False
    )
    assert not issued_cookie
    assert not issued_json
    assert "set-cookie" not in response.headers
    assert response.template.name == "signin.html"
    assert response.context["user"] is None
    message = response.context["language"]["Incorrect-username-or-password"]
    assert response.context["language"]["warning"] == message
    assert message in unescape(response.text)
    assert _snapshot(db, app_modules.models) == before


@pytest.mark.parametrize("role", ["ordinary", "admin"])
def test_inactive_key_secret_login_is_denied(
    role, client, db, user, admin, app_modules
):
    """Valid API credentials do not override the owner's inactive state."""
    account = admin if role == "admin" else user
    issued = app_modules.crud.create_new_token(
        db, account.id, "synthetic inactive-account probe"
    )
    account.is_active = False
    db.commit()
    before = _snapshot(db, app_modules.models)
    response = client.post("/token-signin", data=issued)
    minted = bool(response.json().get("access_token"))
    assert not minted
    assert response.status_code == 200
    assert response.json() == {"Auth": "Error"}
    assert "set-cookie" not in response.headers
    assert "access_token" not in client.cookies
    assert _snapshot(db, app_modules.models) == before


def _issue_jwt(channel, client, db, account, password, app_modules):
    """Issue a genuine JWT through the requested channel while the account is active."""
    assert account.is_active is True
    if channel == "key-secret":
        issued = app_modules.crud.create_new_token(
            db, account.id, "synthetic JWT source"
        )
        response = client.post("/token-signin", data=issued)
    else:
        response = client.post(
            "/signin",
            data={
                "username": account.email,
                "password": password,
                **({"scope": "cli"} if channel == "cli" else {}),
            },
        )
    assert response.status_code == 200
    if channel == "web":
        cookies = SimpleCookie()
        cookies.load(response.headers["set-cookie"])
        token = cookies["access_token"].value.removeprefix("Bearer ")
    else:
        token = response.json()["access_token"]
    claims = app_modules.auth.jwt.decode(
        token,
        app_modules.settings.settings.JWT_SECRET,
        algorithms=[app_modules.settings.settings.ALGORITHM],
    )
    assert claims["sub"] == str(account.id)
    return token


def _restore_auth(client, channel, token):
    """Replay the original JWT, not the deleted cookie returned by a previous refusal."""
    client.cookies.clear()
    client.headers.pop("Authorization", None)
    if channel == "web":
        # Match the host/path of cookies issued by this TestClient, including logout scope.
        client.cookies.set(
            "access_token", f"Bearer {token}", domain="testserver.local", path="/"
        )
    else:
        client.headers["Authorization"] = f"Bearer {token}"


@pytest.mark.parametrize("channel", ["web", "cli", "key-secret"])
@pytest.mark.parametrize("role", ["ordinary", "admin"])
def test_deactivation_blocks_existing_jwt_on_reads_and_mutations(
    channel,
    role,
    client,
    db,
    user,
    other_user,
    admin,
    password,
    app_modules,
):
    """Every request reloads active state; a still-valid signature grants no inactive access."""
    account = admin if role == "admin" else user
    ip = app_modules.crud.create_user_ip(db, account.id, "198.51.100.30", ttl_hours=3)
    link = app_modules.crud.create_instant_access(
        db, "https://example.com/private", account.id, ttl_hours=3
    )
    saved_token = app_modules.models.Token(
        owner_id=account.id,
        key="synthetic-deletion-target",
        secret=account.hashed_password,
    )
    db.add(saved_token)
    db.commit()
    jwt = _issue_jwt(channel, client, db, account, password, app_modules)
    _restore_auth(client, channel, jwt)
    assert client.get("/ips/config/", headers={"Cli": "true"}).status_code == 200
    account.is_active = False
    db.commit()
    before = _snapshot(db, app_modules.models)
    # The JWT remains cryptographically valid; refusal must come from current DB state.
    assert app_modules.auth.jwt.decode(
        jwt,
        app_modules.settings.settings.JWT_SECRET,
        algorithms=[app_modules.settings.settings.ALGORITHM],
    )["sub"] == str(account.id)
    requests = [
        ("GET", "/ips/config/", {}),
        ("GET", "/ips/config/", {"headers": {"Cli": "true"}}),
        ("GET", "/instant-access/config/", {}),
        ("GET", f"/users/details/{account.id}", {}),
        ("GET", "/users/read", {}),
        ("GET", f"/users/reset_password/{account.id}", {}),
        ("GET", "/docs", {}),
        ("GET", "/openapi.json", {}),
        ("POST", "/ips/config/", {"data": {"action": "delete", "ip_id": ip.id}}),
        (
            "POST",
            "/instant-access/config/",
            {"data": {"action": "delete", "link_id": link.id}},
        ),
        (
            "POST",
            f"/users/details/{account.id}",
            {
                "data": {
                    "action": "delete",
                    "token_id": saved_token.id,
                }
            },
        ),
        (
            "POST",
            f"/users/details/{account.id}",
            {
                "data": {
                    "token": "true",
                    "twofactor": "true",
                    "ip_default_ttl_hours": "6",
                }
            },
        ),
        (
            "POST",
            f"/users/reset_password/{account.id}",
            {
                "data": {
                    "password": "Changed-pass-43!",
                    "confirm_password": "Changed-pass-43!",
                }
            },
        ),
        ("POST", "/users/read", {"data": {"email": account.email}}),
    ]
    for method, path, kwargs in requests:
        _restore_auth(client, channel, jwt)
        response = client.request(method, path, **kwargs)
        assert response.status_code == 302, (method, path)
        assert response.headers["location"] == "/logout"
        assert response.json() == {"detail": "Could not validate credentials"}
        assert _snapshot(db, app_modules.models) == before


@pytest.mark.parametrize("channel", ["web", "cli"])
@pytest.mark.parametrize("role", ["ordinary", "admin"])
def test_valid_totp_cannot_reactivate_inactive_account(
    channel,
    role,
    client,
    db,
    user,
    admin,
    password,
    totp_time,
    app_modules,
):
    """Even a current correct second factor cannot authorize an inactive account."""
    import pyotp

    account = admin if role == "admin" else user
    account.twofactor = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    account.is_active = False
    db.commit()
    code = pyotp.TOTP(account.twofactor).at(totp_time)
    before = _snapshot(db, app_modules.models)
    response = client.post(
        "/signin",
        data={
            "username": account.email,
            "password": password,
            "two_factor_code": code,
            **({"scope": "cli"} if channel == "cli" else {}),
        },
    )
    assert response.status_code == 200
    assert response.context["user"] is None
    assert (
        response.context["language"]["warning"]
        == response.context["language"]["Incorrect-username-or-password"]
    )
    assert "access_token" not in client.cookies
    assert "set-cookie" not in response.headers
    assert _snapshot(db, app_modules.models) == before


def test_inactive_cookie_is_not_rescued_by_another_active_bearer(
    client,
    db,
    user,
    other_user,
    password,
    app_modules,
):
    """Cookie precedence stays fail-closed; a second identity cannot rescue a refused cookie."""
    token = _issue_jwt("web", client, db, user, password, app_modules)
    active_token = _issue_jwt("cli", client, db, other_user, password, app_modules)
    user.is_active = False
    db.commit()
    before = _snapshot(db, app_modules.models)
    _restore_auth(client, "web", token)
    response = client.get(
        "/ips/config/", headers={"Authorization": f"Bearer {active_token}"}
    )
    assert response.status_code == 302
    assert _snapshot(db, app_modules.models) == before
    _restore_auth(client, "cli", active_token)
    active = client.get(f"/users/details/{other_user.id}")
    assert active.status_code == 200
    assert active.context["user"].id == other_user.id
    assert _snapshot(db, app_modules.models) == before


def test_inactive_cookie_is_rejected_by_optional_auth_pages(
    client,
    db,
    user,
    password,
    app_modules,
):
    """Public pages must not render an inactive cookie holder as authenticated."""
    token = _issue_jwt("web", client, db, user, password, app_modules)
    user.is_active = False
    db.commit()
    before = _snapshot(db, app_modules.models)
    for path in ("/", "/signin", "/register"):
        _restore_auth(client, "web", token)
        response = client.get(path)
        assert response.status_code == 302
        assert response.headers["location"] == "/logout"
        assert _snapshot(db, app_modules.models) == before
    response = client.get("/logout")
    assert response.status_code == 200
    assert "access_token" not in client.cookies
    assert _snapshot(db, app_modules.models) == before


def test_api_key_without_owner_is_refused(client, db, user, password, app_modules):
    """A dangling key cannot authenticate or crash when its owner cannot be loaded."""
    db.add(
        app_modules.models.Token(
            owner_id=user.id + 1000,
            key="synthetic-orphan-key",
            secret=user.hashed_password,
        )
    )
    db.commit()
    before = _snapshot(db, app_modules.models)
    response = client.post(
        "/token-signin", data={"key": "synthetic-orphan-key", "secret": password}
    )
    assert response.status_code == 200
    assert response.json() == {"Auth": "Error"}
    assert "access_token" not in client.cookies
    assert _snapshot(db, app_modules.models) == before
