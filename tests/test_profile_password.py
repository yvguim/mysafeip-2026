"""Exercise the password action exposed in the authenticated profile."""

import pytest


@pytest.mark.parametrize(
    ("language", "label"),
    [("fr", "Changer le mot de passe"), ("en", "Change password")],
)
@pytest.mark.parametrize("role", ["user", "admin"])
def test_own_profile_links_to_password_form(
    language, label, role, client, user, admin, login
):
    account = admin if role == "admin" else user
    login(client, account)
    client.cookies.set("lang", language)
    profile = client.get(f"/users/details/{account.id}")
    path = f"/users/reset_password/{account.id}"
    assert profile.status_code == 200
    assert f'href="{path}">{label}</a>' in profile.text
    assert client.get(path).template.name == "reset_password.html"


def test_admin_viewing_another_profile_has_no_self_service_action(
    client, user, admin, login
):
    login(client, admin)
    profile = client.get(f"/users/details/{user.id}")
    assert profile.status_code == 200
    assert f'href="/users/reset_password/{user.id}"' not in profile.text


@pytest.mark.parametrize("role", ["user", "admin"])
@pytest.mark.parametrize("credential", [None, "Wrong-test-only-42!"])
def test_own_password_change_requires_current_credential(
    role, credential, client, user, admin, login, db
):
    account = admin if role == "admin" else user
    login(client, account)
    path = f"/users/reset_password/{account.id}"
    form = client.get(path)
    assert 'name="current_password" autocomplete="current-password"' in form.text
    assert 'autocomplete="new-password"' in form.text
    assert form.headers["cache-control"] == "no-store"
    original_hash = account.hashed_password
    replacement = "Profile-test-only-52!"
    data = {"password": replacement, "confirm_password": replacement}
    if credential is not None:
        data["current_password"] = credential
    response = client.post(path, data=data)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    language = response.context["language"]
    assert language["warning"] == language["Incorrect-current-password"]
    assert replacement not in response.text
    if credential is not None:
        assert credential not in response.text
    db.refresh(account)
    assert account.hashed_password == original_hash


def test_admin_can_still_reset_another_account_without_its_current_password(
    admin, user, client, login
):
    login(client, admin)
    form = client.get(f"/users/reset_password/{user.id}")
    assert 'name="current_password"' not in form.text


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_reset_for_unknown_account_returns_not_found(method, client, admin, login):
    login(client, admin)
    data = {
        "password": "Profile-test-only-52!",
        "confirm_password": "Profile-test-only-52!",
    }
    response = client.request(
        method, f"/users/reset_password/{admin.id + 1}", data=data
    )
    assert response.status_code == 404


def test_password_change_does_not_overwrite_a_newer_reset(app_modules, db, user):
    original_hash = user.hashed_password
    with app_modules.database.SessionLocal() as other_session:
        account = other_session.get(app_modules.models.User, user.id)
        assert app_modules.crud.reset_user_password(
            other_session, account, "Other-test-93!"
        )
        new_hash = account.hashed_password
    assert user.hashed_password == original_hash
    assert not app_modules.crud.reset_user_password(db, user, "Stale-test-43!")
    db.refresh(user)
    assert user.hashed_password == new_hash
