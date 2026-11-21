"""Characterize account authorization and persisted user-management behavior."""

from urllib.parse import parse_qs, urlparse

import pytest

pytestmark = pytest.mark.characterization


def _assert_message(response, level, key):
    assert response.context["language"][level] == response.context["language"][key]


@pytest.mark.parametrize("role", ["normal", "admin"])
def test_current_user_list_behavior(
    role, client, user, other_user, admin, login, db, app_modules
):
    """Admin gets accounts; normal access renders a warning without exposing other users."""
    current = admin if role == "admin" else user
    login(client, current)
    response = client.get("/users/read")
    assert response.status_code == 200
    assert response.template.name == "users.html"
    assert response.context["user"].id == current.id
    if role == "normal":
        _assert_message(response, "warning", "Only-admin-can-get-users")
        assert response.context["users"] == []
        assert other_user.email not in response.text
        assert admin.email not in response.text
        assert db.query(app_modules.models.User).count() == 3
        return
    assert {item.id for item in response.context["users"]} == {
        user.id,
        other_user.id,
        admin.id,
    }
    assert other_user.email in response.text


@pytest.mark.parametrize("path", ["/docs", "/openapi.json"])
@pytest.mark.parametrize("role", ["anonymous", "normal", "admin"])
def test_documentation_requires_admin(role, path, client, user, admin, login):
    if role != "anonymous":
        login(client, admin if role == "admin" else user)
    response = client.get(path)
    if role == "anonymous":
        assert response.status_code == 401
        assert response.json() == {"detail": "Not authenticated"}
        assert response.headers["www-authenticate"] == "Bearer"
    elif role == "normal":
        assert response.status_code == 401
        expected = (
            "Only admins can use fastapi docs"
            if path == "/docs"
            else "Only admins can use openapi.json"
        )
        assert response.json() == {"detail": expected}
    elif path == "/docs":
        assert response.status_code == 200
        assert "SwaggerUIBundle" in response.text
        assert "/openapi.json" in response.text
    else:
        assert response.status_code == 200
        schema = response.json()
        assert schema["openapi"].startswith("3.")
        assert "/users/read" in schema["paths"]
        assert "/signin" in schema["paths"]


@pytest.mark.parametrize("method", ["get", "post"])
def test_normal_user_cannot_reset_another_password(
    method,
    client,
    user,
    other_user,
    login,
    db,
    app_modules,
):
    login(client, user)
    original_hash = other_user.hashed_password
    path = f"/users/reset_password/{other_user.id}"
    response = (
        client.get(path)
        if method == "get"
        else client.post(
            path,
            data={
                "password": "Changed-pass-43!",
                "confirm_password": "Changed-pass-43!",
            },
        )
    )
    assert response.status_code == 200
    assert response.template.name == "reset_password.html"
    assert response.context["user"] is False
    _assert_message(response, "danger", "You-are-not-allowed-to-do-this")
    db.expire_all()
    assert (
        db.get(app_modules.models.User, other_user.id).hashed_password == original_hash
    )


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_authorized_reset_persists_hash_and_changes_real_login(
    role,
    client,
    client_factory,
    user,
    admin,
    login,
    db,
    app_modules,
    password,
):
    current = user if role == "owner" else admin
    login(client, current)
    page = client.get(f"/users/reset_password/{user.id}")
    assert page.template.name == "reset_password.html"
    assert page.context["user"].id == user.id
    replacement = "Changed-pass-43!"
    response = client.post(
        f"/users/reset_password/{user.id}",
        data={
            "password": replacement,
            "confirm_password": replacement,
        },
    )
    assert response.status_code == 200
    _assert_message(response, "success", "Password-reset-successfull")
    db.expire_all()
    saved = db.get(app_modules.models.User, user.id)
    assert saved.hashed_password != replacement
    assert app_modules.security.verify_password(replacement, saved.hashed_password)
    assert not app_modules.security.verify_password(password, saved.hashed_password)
    fresh = client_factory()
    rejected = fresh.post(
        "/signin", data={"username": user.email, "password": password}
    )
    assert rejected.status_code == 200
    assert rejected.context["user"] is None
    _assert_message(rejected, "warning", "Incorrect-username-or-password")
    assert "access_token" not in fresh.cookies
    new_login = fresh.post(
        "/signin", data={"username": user.email, "password": replacement}
    )
    assert new_login.context["user"].id == user.id
    assert "access_token" in fresh.cookies


@pytest.mark.parametrize("case", ["short", "confirmation"])
def test_invalid_own_password_reset_leaves_hash_unchanged(
    case,
    client,
    user,
    login,
    db,
    app_modules,
):
    login(client, user)
    original_hash = user.hashed_password
    replacement = "Ab1!" if case == "short" else "Changed-pass-43!"
    confirmation = replacement if case == "short" else "different"
    response = client.post(
        f"/users/reset_password/{user.id}",
        data={
            "password": replacement,
            "confirm_password": confirmation,
        },
    )
    assert response.status_code == 200
    assert response.template.name == "reset_password.html"
    _assert_message(
        response,
        "warning",
        "Password-help" if case == "short" else "Password-missmatch",
    )
    db.expire_all()
    assert db.get(app_modules.models.User, user.id).hashed_password == original_hash


def test_self_deletion_removes_owned_children_and_cookie_only(
    client,
    user,
    other_user,
    login,
    db,
    app_modules,
):
    models = app_modules.models
    owner_id = user.id
    other_id = other_user.id
    for account in (user, other_user):
        db.add(
            models.Ip(
                owner_id=account.id,
                value="192.0.2.3",
                description="owned IP",
                origin="manual",
            )
        )
        db.add(
            models.InstantAccess(
                owner_id=account.id,
                unique_link=f"link-{account.id}",
                link="https://example.com",
                description="owned link",
            )
        )
        db.add(
            models.Token(
                owner_id=account.id,
                key=f"key-{account.id}",
                secret=account.hashed_password,
                description="owned token",
            )
        )
    db.commit()
    login(client, user)
    response = client.post("/users/read", data={"email": user.email})
    assert response.status_code == 302
    assert response.headers["location"] == "/"
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert "access_token" not in client.cookies
    db.expire_all()
    assert db.get(models.User, owner_id) is None
    assert db.get(models.User, other_id) is not None
    for model in (models.Ip, models.InstantAccess, models.Token):
        assert db.query(model).filter(model.owner_id == owner_id).count() == 0
        assert db.query(model).filter(model.owner_id == other_id).count() == 1
    assert client.get("/users/read").status_code == 401


def test_admin_self_deletion_renders_warning_without_deleting(
    client,
    admin,
    user,
    login,
    db,
    app_modules,
):
    """An administrator cannot delete their own account; the refusal renders normally."""
    login(client, admin)
    response = client.post("/users/read", data={"email": admin.email})
    assert response.status_code == 200
    assert response.template.name == "users.html"
    _assert_message(response, "warning", "You cant delete your own admin account")
    db.expire_all()
    assert db.get(app_modules.models.User, admin.id).is_admin is True
    assert db.query(app_modules.models.User).count() == 2
    assert "access_token" in client.cookies


def test_normal_user_cannot_delete_another_account(
    client, user, other_user, login, db, app_modules
):
    login(client, user)
    response = client.post("/users/read", data={"email": other_user.email})
    assert response.status_code == 200
    _assert_message(response, "warning", "Only-admin-can-delete-other-users")
    assert response.context["users"] == ""
    db.expire_all()
    assert db.query(app_modules.models.User).count() == 2
    assert db.get(app_modules.models.User, other_user.id) is not None


def test_admin_can_delete_another_account(client, user, admin, login, db, app_modules):
    target_id = user.id
    login(client, admin)
    response = client.post("/users/read", data={"email": user.email})
    assert response.status_code == 200
    assert response.template.name == "users.html"
    assert response.context["language"]["success"]
    assert {item.id for item in response.context["users"]} == {admin.id}
    db.expire_all()
    assert db.get(app_modules.models.User, target_id) is None
    assert db.get(app_modules.models.User, admin.id) is not None
    assert "access_token" in client.cookies


def test_details_ignore_other_id_and_do_not_leak_other_tokens(
    client,
    user,
    other_user,
    login,
    db,
    app_modules,
):
    db.add(
        app_modules.models.Token(
            owner_id=user.id, key="alice-key", secret=user.hashed_password
        )
    )
    db.add(
        app_modules.models.Token(
            owner_id=other_user.id,
            key="bob-private-key",
            secret=other_user.hashed_password,
        )
    )
    db.commit()
    login(client, user)
    response = client.get(f"/users/details/{other_user.id}")
    assert response.status_code == 200
    assert response.template.name == "user-details.html"
    assert response.context["user"].id == user.id
    assert {token.key for token in response.context["tokens"]} == {"alice-key"}
    assert other_user.email not in response.text
    assert "bob-private-key" not in response.text
    assert "alice-key" in response.text


def test_admin_can_view_selected_account(client, admin, user, login):
    login(client, admin)
    response = client.get(f"/users/details/{user.id}")
    assert response.status_code == 200
    assert response.context["user"].id == user.id
    assert user.email in response.text


def test_token_creation_hashes_secret_and_only_shows_plaintext_once(
    client,
    user,
    login,
    db,
    app_modules,
):
    login(client, user)
    response = client.post(
        f"/users/details/{user.id}",
        data={"token": "true", "description": "test client"},
    )
    assert response.status_code == 200
    issued = response.context["newtoken"]
    assert set(issued) == {"key", "secret"}
    assert len(issued["key"]) == 32
    assert len(issued["secret"]) == 64
    db.expire_all()
    saved = db.query(app_modules.models.Token).one()
    assert saved.owner_id == user.id
    assert saved.key == issued["key"]
    assert saved.description == "test client"
    assert saved.secret != issued["secret"]
    assert app_modules.security.verify_password(issued["secret"], saved.secret)
    assert issued["secret"] in response.text
    page = client.get(f"/users/details/{user.id}")
    assert issued["secret"] not in page.text
    assert saved.secret not in page.text
    assert saved.key in page.text


def test_delete_own_token_preserves_totp_and_revokes_key_signin(
    client,
    user,
    login,
    db,
    app_modules,
):
    login(client, user)
    issued = app_modules.crud.create_new_token(db, user.id, "delete me")
    token_id = db.query(app_modules.models.Token).one().id
    user.twofactor = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    db.commit()
    response = client.post(
        f"/users/details/{user.id}",
        data={"action": "delete", "token_id": str(token_id)},
    )
    assert response.status_code == 200
    _assert_message(response, "success", "Instant-link-deleted-successfully")
    db.expire_all()
    assert db.get(app_modules.models.Token, token_id) is None
    assert (
        db.get(app_modules.models.User, user.id).twofactor
        == "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    )
    assert client.post("/token-signin", data=issued).json() == {"Auth": "Error"}


@pytest.mark.parametrize(
    "ip_ttl,ia_ttl,expected",
    [
        ("24", "168", (24, 168)),
        ("0", "168", (1, 24)),
        ("not-an-int", "168", (1, 24)),
    ],
)
def test_ttl_update_targets_current_user_even_with_other_id(
    ip_ttl,
    ia_ttl,
    expected,
    client,
    user,
    other_user,
    login,
    db,
    app_modules,
):
    login(client, user)
    response = client.post(
        f"/users/details/{other_user.id}",
        data={
            "ip_default_ttl_hours": ip_ttl,
            "ia_default_ttl_hours": ia_ttl,
        },
    )
    assert response.status_code == 200
    assert response.context["user"].id == user.id
    db.expire_all()
    saved = db.get(app_modules.models.User, user.id)
    assert (saved.ip_default_ttl_hours, saved.ia_default_ttl_hours) == expected
    untouched = db.get(app_modules.models.User, other_user.id)
    assert (untouched.ip_default_ttl_hours, untouched.ia_default_ttl_hours) == (1, 24)


def test_explicit_totp_activation_is_persistent_and_does_not_rotate_existing_secret(
    client,
    user,
    login,
    db,
    app_modules,
):
    login(client, user)
    response = client.post(f"/users/details/{user.id}", data={"twofactor": "true"})
    assert response.status_code == 200
    db.expire_all()
    saved = db.get(app_modules.models.User, user.id)
    secret = saved.twofactor
    assert len(secret) == 32
    uri = urlparse(response.context["twofactorurl"])
    assert uri.scheme == "otpauth"
    assert uri.netloc == "totp"
    params = parse_qs(uri.query)
    assert params["secret"] == [secret]
    assert params["issuer"] == ["MySafeIP"]
    repeat = client.post(f"/users/details/{user.id}", data={"twofactor": "true"})
    assert repeat.context["twofactorurl"] == ""
    db.expire_all()
    assert db.get(app_modules.models.User, user.id).twofactor == secret


def test_explicit_totp_deactivation_persists_empty_secret(
    client, user, login, db, app_modules
):
    login(client, user)
    user.twofactor = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    db.commit()
    response = client.post(
        f"/users/details/{user.id}",
        data={"twofactor_settings": "true", "twofactor": ""},
    )
    assert response.status_code == 200
    assert response.context["twofactorurl"] == ""
    db.expire_all()
    assert db.get(app_modules.models.User, user.id).twofactor == ""
    assert response.context["user"].twofactor == ""
