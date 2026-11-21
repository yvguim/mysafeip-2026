"""Desired rejection responses for additional defects discovered by the suite."""

from html import unescape

import pytest


@pytest.mark.characterization
@pytest.mark.parametrize("language", ["en", "fr"])
@pytest.mark.parametrize("mode", ["web", "cli"])
@pytest.mark.parametrize("bad_field", ["username", "password"])
def test_invalid_signin_returns_a_refusal_without_server_error(
    client,
    user,
    password,
    db,
    app_modules,
    language,
    mode,
    bad_field,
):
    """Reject invalid credentials in both modes without rendering errors or a session (#10)."""
    client.cookies.set("lang", language)
    data = {"username": user.email, "password": password}
    if mode == "cli":
        data["scope"] = "cli"
    data[bad_field] = (
        "missing@example.com" if bad_field == "username" else "Wrong-only-42!"
    )
    original_hash = user.hashed_password
    response = client.post("/signin", data=data)
    assert response.status_code == 200
    assert response.template.name == "signin.html"
    assert response.context["user"] is None
    translations = app_modules.auth.check_user_language(
        response.context["request"], lang=language
    )
    warning = translations["Incorrect-username-or-password"]
    assert response.context["language"]["warning"] == warning
    assert warning in unescape(response.text)
    assert 'name="password" value=""' in response.text
    assert "set-cookie" not in response.headers
    assert "access_token" not in client.cookies
    assert client.get("/users/read").status_code == 401
    db.expire_all()
    assert db.query(app_modules.models.User).count() == 1
    assert db.get(app_modules.models.User, user.id).hashed_password == original_hash


@pytest.mark.characterization
@pytest.mark.parametrize("language", ["en", "fr"])
@pytest.mark.parametrize("operation", ["normal_list", "admin_self_delete"])
def test_user_management_refusals_render_without_missing_translation(
    client,
    user,
    other_user,
    admin,
    login,
    db,
    app_modules,
    language,
    operation,
):
    """Render translated refusals without exposing accounts or mutating them (#11)."""
    client.cookies.set("lang", language)
    login(client, user if operation == "normal_list" else admin)
    session_cookie = client.cookies["access_token"]
    original_accounts = {
        account.id: (
            account.email,
            account.hashed_password,
            account.is_admin,
            account.is_active,
            account.twofactor,
        )
        for account in db.query(app_modules.models.User).all()
    }
    expected_key = (
        "Only-admin-can-get-users"
        if operation == "normal_list"
        else "You cant delete your own admin account"
    )
    if operation == "normal_list":
        response = client.get("/users/read")
    else:
        response = client.post("/users/read", data={"email": admin.email})
    assert response.status_code == 200
    assert response.template.name == "users.html"
    translations = app_modules.auth.check_user_language(
        response.context["request"], lang=language
    )
    warning = translations[expected_key]
    assert response.context["language"]["warning"] == warning
    assert warning in unescape(response.text)
    assert "set-cookie" not in response.headers
    assert client.cookies["access_token"] == session_cookie
    assert response.context["user"].id == (
        user.id if operation == "normal_list" else admin.id
    )
    db.expire_all()
    assert {
        account.id: (
            account.email,
            account.hashed_password,
            account.is_admin,
            account.is_active,
            account.twofactor,
        )
        for account in db.query(app_modules.models.User).all()
    } == original_accounts
    if operation == "normal_list":
        assert response.context["users"] == []
        assert other_user.email not in response.text
        assert admin.email not in response.text
    else:
        assert {account.id for account in response.context["users"]} == set(
            original_accounts
        )
