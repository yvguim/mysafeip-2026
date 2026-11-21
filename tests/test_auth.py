"""Characterize current authentication using real cookies, JWTs and bcrypt."""

from datetime import timedelta
from http.cookies import SimpleCookie

import pytest

pytestmark = pytest.mark.characterization


def _claims(app_modules, token):
    if token.startswith('"'):
        cookie = SimpleCookie()
        cookie.load(f"access_token={token}")
        token = cookie["access_token"].value
    return app_modules.auth.jwt.decode(
        token.removeprefix("Bearer "),
        app_modules.settings.settings.JWT_SECRET,
        algorithms=[app_modules.settings.settings.ALGORITHM],
    )


def _assert_cookie(response):
    cookies = SimpleCookie()
    cookies.load(response.headers["set-cookie"])
    cookie = cookies["access_token"]
    assert cookie.value.startswith("Bearer ")
    assert cookie["httponly"]
    assert cookie["samesite"] == "lax"
    assert cookie["path"] == "/"
    # Characterization: production currently does not set Secure or a max age.
    assert not cookie["secure"]
    assert cookie["max-age"] == ""


def test_registration_persists_bcrypt_nonadmin_and_authenticates(
    client, db, app_modules, password
):
    response = client.post(
        "/register",
        data={
            "email": "new@example.com",
            "password": password,
            "confirm_password": password,
            "is_admin": "true",
        },
    )
    assert response.status_code == 200
    assert response.template.name == "register.html"
    assert response.context["language"]["success"]
    db.expire_all()
    saved = db.query(app_modules.models.User).one()
    assert saved.email == "new@example.com"
    assert saved.is_admin is False
    assert saved.is_active is True
    assert saved.hashed_password != password
    assert saved.hashed_password.startswith("$2")
    assert app_modules.security.verify_password(password, saved.hashed_password)
    assert response.context["user"].id == saved.id
    _assert_cookie(response)
    claims = _claims(app_modules, client.cookies["access_token"])
    assert claims["sub"] == str(saved.id)
    assert claims["type"] == "access_token"
    assert claims["exp"] > claims["iat"]
    assert client.get(f"/users/details/{saved.id}").context["user"].id == saved.id


@pytest.mark.parametrize(
    "case",
    [
        "duplicate",
        "email",
        "short",
        "lowercase",
        "uppercase",
        "no_digit",
        "no_symbol",
        "confirmation",
    ],
)
def test_registration_rejects_invalid_input_without_creating_user(
    case,
    client,
    user,
    db,
    app_modules,
    password,
):
    original_hash = user.hashed_password
    email = user.email if case == "duplicate" else "new@example.com"
    if case == "email":
        email = "not-an-email"
    submitted = {
        "short": "Aa1!",
        "lowercase": "abcdef1!",
        "uppercase": "ABCDEF1!",
        "no_digit": "Abcdefg!",
        "no_symbol": "Abcdef12",
    }.get(case, password)
    confirmation = "different" if case == "confirmation" else submitted
    response = client.post(
        "/register",
        data={
            "email": email,
            "password": submitted,
            "confirm_password": confirmation,
        },
    )
    assert response.status_code == 200
    assert response.template.name == "register.html"
    assert response.context["language"].get("warning") or response.context[
        "language"
    ].get("danger")
    assert "access_token" not in client.cookies
    db.expire_all()
    assert db.query(app_modules.models.User).count() == 1
    assert db.get(app_modules.models.User, user.id).hashed_password == original_hash


def test_registration_disabled_shows_warning_and_does_not_persist(
    client,
    db,
    app_modules,
    password,
    monkeypatch,
):
    monkeypatch.setattr(app_modules.settings.settings, "DISABLE_REGISTER", True)
    page = client.get("/register")
    assert (
        page.context["language"]["warning"]
        == page.context["language"]["Registering-disabled"]
    )
    response = client.post(
        "/register",
        data={
            "email": "new@example.com",
            "password": password,
            "confirm_password": password,
        },
    )
    assert (
        response.context["language"]["warning"]
        == response.context["language"]["Account-creation-error"]
    )
    db.expire_all()
    assert db.query(app_modules.models.User).count() == 0
    assert "access_token" not in client.cookies


def test_authenticated_registration_does_not_create_second_account(
    client,
    user,
    login,
    db,
    app_modules,
    password,
):
    login(client, user)
    old_cookie = client.cookies["access_token"]
    response = client.post(
        "/register",
        data={
            "email": "new@example.com",
            "password": password,
            "confirm_password": password,
        },
    )
    assert (
        response.context["language"]["warning"]
        == response.context["language"]["Account-creation-error"]
    )
    db.expire_all()
    assert db.query(app_modules.models.User).count() == 1
    assert client.cookies["access_token"] == old_cookie


def test_web_signin_sets_cookie_and_claims(client, user, password, app_modules, db):
    original_hash = user.hashed_password
    response = client.post(
        "/signin", data={"username": user.email, "password": password}
    )
    assert response.status_code == 200
    assert response.template.name == "signin.html"
    assert response.context["user"].id == user.id
    assert (
        response.context["language"]["success"]
        == response.context["language"]["Signin-success"]
    )
    _assert_cookie(response)
    claims = _claims(app_modules, client.cookies["access_token"])
    assert claims["sub"] == str(user.id)
    assert claims["type"] == "access_token"
    assert (
        claims["exp"] - claims["iat"]
        == app_modules.settings.settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    db.expire_all()
    assert db.get(app_modules.models.User, user.id).hashed_password == original_hash


@pytest.mark.parametrize("bad_field", ["username", "password"])
def test_bad_credentials_render_warning_without_authenticating(
    client,
    user,
    password,
    bad_field,
    db,
    app_modules,
):
    """Invalid credentials render the ordinary sign-in refusal without authentication."""
    data = {"username": user.email, "password": password}
    data[bad_field] = (
        "absent@example.com" if bad_field == "username" else "Wrong-pass-99!"
    )
    response = client.post("/signin", data=data)
    assert response.status_code == 200
    assert response.context["user"] is None
    assert (
        response.context["language"]["warning"]
        == response.context["language"]["Incorrect-username-or-password"]
    )
    assert "access_token" not in client.cookies
    db.expire_all()
    assert db.query(app_modules.models.User).count() == 1


def test_cli_signin_returns_bearer_without_cookie(client, user, password, app_modules):
    response = client.post(
        "/signin", data={"username": user.email, "password": password, "scope": "cli"}
    )
    assert response.status_code == 200
    assert set(response.json()) == {"access_token"}
    token = response.json()["access_token"]
    assert _claims(app_modules, token)["sub"] == str(user.id)
    assert "access_token" not in client.cookies
    assert "set-cookie" not in response.headers
    page = client.get(
        f"/users/details/{user.id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert page.context["user"].id == user.id


@pytest.mark.parametrize("code_kind", ["valid", "missing", "wrong"])
def test_totp_signin_requires_current_code(
    code_kind,
    client,
    user,
    password,
    db,
    totp_time,
    app_modules,
):
    import pyotp

    user.twofactor = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    db.commit()
    valid = pyotp.TOTP(user.twofactor).at(totp_time)
    wrong = str((int(valid) + 1) % 1000000).zfill(6)
    data = {"username": user.email, "password": password}
    if code_kind != "missing":
        data["two_factor_code"] = valid if code_kind == "valid" else wrong
    response = client.post("/signin", data=data)
    assert response.status_code == 200
    assert response.template.name == "signin.html"
    if code_kind == "valid":
        assert response.context["user"].id == user.id
        assert _claims(app_modules, client.cookies["access_token"])["sub"] == str(
            user.id
        )
    else:
        assert response.context["user"] is None
        assert (
            response.context["language"]["warning"]
            == response.context["language"]["Incorrect-totp"]
        )
        assert "access_token" not in client.cookies
    db.expire_all()
    assert (
        db.get(app_modules.models.User, user.id).twofactor
        == "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    )


@pytest.mark.parametrize(
    "language,warning", [("fr", "Code OTP incorrect"), ("en", "Incorrect OTP code")]
)
@pytest.mark.parametrize("scope", ["", "cli"])
def test_short_totp_secret_fails_closed(
    client, user, password, db, app_modules, language, warning, scope
):
    """A stored short secret must not cause a 500, clear TOTP or grant a session."""
    from base64 import b32encode

    from sqlalchemy import select

    short_secret = b32encode(b"\x01" * 13).decode().rstrip("=")
    user.twofactor = short_secret
    db.commit()
    tables = tuple(app_modules.models.Base.metadata.sorted_tables)
    before = [db.execute(select(table)).all() for table in tables]
    client.cookies.set("lang", language)
    response = client.post(
        "/signin",
        data={
            "username": user.email,
            "password": password,
            "scope": scope,
            "two_factor_code": "123456",
        },
    )
    assert response.status_code == 200
    assert response.template.name == "signin.html"
    assert response.context["user"] is None
    assert response.context["language"]["warning"] == warning
    assert "access_token" not in client.cookies
    db.expire_all()
    assert [db.execute(select(table)).all() for table in tables] == before


@pytest.mark.parametrize("credentials", ["valid", "unknown_key", "wrong_secret"])
def test_key_secret_signin_uses_stored_hash(credentials, client, user, db, app_modules):
    issued = app_modules.crud.create_new_token(db, user.id, "automation")
    saved = db.query(app_modules.models.Token).one()
    saved_hash = saved.secret
    assert saved_hash != issued["secret"]
    assert app_modules.security.verify_password(issued["secret"], saved_hash)
    data = dict(issued)
    if credentials == "unknown_key":
        data["key"] = "missing-key"
    elif credentials == "wrong_secret":
        data["secret"] = "incorrect-secret"
    response = client.post("/token-signin", data=data)
    assert response.status_code == 200
    assert "access_token" not in client.cookies
    if credentials == "valid":
        token = response.json()["access_token"]
        assert _claims(app_modules, token)["sub"] == str(user.id)
        page = client.get(
            f"/users/details/{user.id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert page.status_code == 200
        assert page.context["user"].id == user.id
    else:
        assert response.json() == {"Auth": "Error"}
    db.expire_all()
    assert db.query(app_modules.models.Token).one().secret == saved_hash


@pytest.mark.parametrize("authorization", [None, "Basic unsupported"])
def test_protected_route_without_bearer_returns_401(client, authorization):
    headers = {} if authorization is None else {"Authorization": authorization}
    response = client.get("/users/read", headers=headers)
    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}
    assert response.headers["www-authenticate"] == "Bearer"
    assert "location" not in response.headers


@pytest.mark.parametrize(
    "kind", ["malformed", "expired", "missing_sub", "missing_user"]
)
def test_invalid_jwt_redirects_to_logout_with_current_cookie_header(
    client, user, app_modules, kind
):
    auth = app_modules.auth
    if kind == "malformed":
        token = "not.a.jwt"
    elif kind == "expired":
        token = auth._create_token(
            token_type="access_token", lifetime=timedelta(seconds=-60), sub=user.id
        )
    elif kind == "missing_sub":
        token = auth.jwt.encode(
            {"type": "access_token"},
            auth.settings.JWT_SECRET,
            algorithm=auth.settings.ALGORITHM,
        )
    else:
        token = auth.create_access_token(sub=user.id + 1000)
    response = client.get("/users/read", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 302
    assert response.headers["location"] == "/logout"
    assert response.headers["set-cookie"] == "access_token=deleted"
    assert response.json() == {"detail": "Could not validate credentials"}


def test_cookie_identity_takes_precedence_over_other_valid_bearer(
    client,
    user,
    other_user,
    login,
    app_modules,
):
    login(client, user)
    token = app_modules.auth.create_access_token(sub=other_user.id)
    response = client.get(
        f"/users/details/{other_user.id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.context["user"].id == user.id
    assert other_user.email not in response.text


def test_invalid_cookie_is_not_rescued_by_valid_bearer(client, user, app_modules):
    client.cookies.set("access_token", "Bearer not.a.jwt")
    token = app_modules.auth.create_access_token(sub=user.id)
    response = client.get("/users/read", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 302
    assert response.headers["location"] == "/logout"
    assert response.headers["set-cookie"] == "access_token=deleted"


def test_logout_expires_cookie_but_does_not_delete_account(
    client, user, login, db, app_modules
):
    login(client, user)
    response = client.get("/logout")
    assert response.status_code == 200
    assert response.template.name == "home.html"
    assert response.context["user"] == ""
    assert (
        response.context["language"]["success"]
        == response.context["language"]["Logout-successfull"]
    )
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert "access_token" not in client.cookies
    assert client.get("/users/read").status_code == 401
    db.expire_all()
    assert db.get(app_modules.models.User, user.id) is not None
