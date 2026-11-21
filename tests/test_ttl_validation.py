"""Issue #5: bounded, uniform TTL form validation without partial mutations."""

from datetime import timedelta
from html import unescape

import pytest

pytestmark = pytest.mark.characterization

INVALID_DURATIONS = [
    "not-a-number",
    "-1",
    "0",
    "721",
    "1.5",
    " ",
    pytest.param("9" * 40, id="overflow"),
    pytest.param("9" * 5000, id="5000-digits"),
]


def _snapshot(db, models):
    """Read all synthetic persisted fields, not cached identity-map state."""
    db.expire_all()
    return {
        model.__name__: [
            tuple(getattr(row, column.name) for column in model.__table__.columns)
            for row in db.query(model).order_by(model.id).all()
        ]
        for model in (models.User, models.Ip, models.InstantAccess, models.Token)
    }


def _resource(resource):
    """Return the public form contract and model for each resource kind."""
    if resource == "ip":
        return "/ips/config/", {"ip": "198.51.100.51"}, "Ip"
    return "/instant-access/config/", {"link": "https://example.com/"}, "InstantAccess"


def _assert_invalid_duration(response):
    """Preserve existing HTML 200 refusal, with an actually rendered warning."""
    assert response.status_code == 200
    language = response.context["language"]
    assert language["warning"] == language["Invalid-duration"]
    assert language["warning"] in unescape(response.text)


@pytest.mark.parametrize("resource", ["ip", "link"])
@pytest.mark.parametrize("mode", ["standard", "custom"])
@pytest.mark.parametrize("duration", INVALID_DURATIONS)
def test_invalid_creation_ttl_is_rejected_without_mutation(
    resource,
    mode,
    duration,
    client,
    login,
    user,
    db,
    app_modules,
    frozen_time,
):
    """Both form paths reject malformed, nonpositive and excessive durations."""
    login(client, user)
    path, fields, _ = _resource(resource)
    ttl = (
        {"ttl_hours": duration}
        if mode == "standard"
        else {
            "ttl_hours": "custom",
            "custom_ttl_hours": duration,
        }
    )
    before = _snapshot(db, app_modules.models)
    response = client.post(path, data={"action": "create", **fields, **ttl})
    _assert_invalid_duration(response)
    assert _snapshot(db, app_modules.models) == before


@pytest.mark.parametrize("resource", ["ip", "link"])
def test_selected_custom_ttl_requires_a_value(
    resource,
    client,
    login,
    user,
    db,
    app_modules,
    frozen_time,
):
    """Selecting custom without a duration must not silently use the default."""
    login(client, user)
    path, fields, _ = _resource(resource)
    before = _snapshot(db, app_modules.models)
    response = client.post(
        path, data={"action": "create", **fields, "ttl_hours": "custom"}
    )
    _assert_invalid_duration(response)
    assert _snapshot(db, app_modules.models) == before


@pytest.mark.parametrize("role", ["owner", "admin"])
@pytest.mark.parametrize("field", ["ip_default_ttl_hours", "ia_default_ttl_hours"])
@pytest.mark.parametrize("duration", INVALID_DURATIONS)
def test_invalid_account_ttl_rejects_the_whole_form(
    role,
    field,
    duration,
    client,
    login,
    user,
    admin,
    other_user,
    db,
    app_modules,
):
    """Validate both TTLs before any account settings can be persisted."""
    actor = user if role == "owner" else admin
    login(client, actor)
    user.twofactor = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    db.commit()
    data = {"ip_default_ttl_hours": "6", "ia_default_ttl_hours": "48", field: duration}
    before = _snapshot(db, app_modules.models)
    response = client.post(f"/users/details/{user.id}", data=data)
    assert _snapshot(db, app_modules.models) == before
    _assert_invalid_duration(response)
    assert response.context["user"].id == user.id
    assert response.context["newtoken"] == ""
    assert response.context["twofactorurl"] == ""


@pytest.mark.parametrize(
    "operation", ["token-create", "token-delete", "totp-enable", "totp-disable"]
)
@pytest.mark.parametrize("field", ["ip_default_ttl_hours", "ia_default_ttl_hours"])
def test_invalid_account_ttl_prevents_other_requested_mutations(
    operation,
    field,
    client,
    login,
    user,
    db,
    app_modules,
):
    """A rejected combined request cannot create/delete a token or toggle TOTP."""
    login(client, user)
    token = app_modules.models.Token(
        owner_id=user.id, key="synthetic-key", secret=user.hashed_password
    )
    db.add(token)
    if operation == "totp-disable":
        user.twofactor = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    db.commit()
    data = {field: "721"}
    data.update(
        {
            "token-create": {"token": "true"},
            "token-delete": {"action": "delete", "token_id": str(token.id)},
            "totp-enable": {"twofactor": "true"},
            "totp-disable": {},
        }[operation]
    )
    before = _snapshot(db, app_modules.models)
    response = client.post(f"/users/details/{user.id}", data=data)
    assert _snapshot(db, app_modules.models) == before
    _assert_invalid_duration(response)


@pytest.mark.parametrize("role", ["owner", "admin"])
@pytest.mark.parametrize(
    "fields,expected",
    [
        ({"ip_default_ttl_hours": "1", "ia_default_ttl_hours": "720"}, (1, 720)),
        ({"ip_default_ttl_hours": "720", "ia_default_ttl_hours": "1"}, (720, 1)),
        ({"ip_default_ttl_hours": "6"}, (6, 24)),
        ({"ia_default_ttl_hours": "48"}, (1, 48)),
    ],
)
def test_valid_account_ttl_supports_bounds_and_independent_fields(
    role,
    fields,
    expected,
    client,
    login,
    user,
    admin,
    other_user,
    db,
    app_modules,
):
    """Valid updates keep the omitted default and target only the authorized account."""
    login(client, user if role == "owner" else admin)
    path_id = other_user.id if role == "owner" else user.id
    before = _snapshot(db, app_modules.models)
    response = client.post(f"/users/details/{path_id}", data=fields)
    assert response.status_code == 200
    assert not response.context["language"].get("warning")
    after = _snapshot(db, app_modules.models)
    saved = db.get(app_modules.models.User, user.id)
    assert (saved.ip_default_ttl_hours, saved.ia_default_ttl_hours) == expected
    assert db.get(app_modules.models.User, other_user.id).ip_default_ttl_hours == 1
    assert db.get(app_modules.models.User, other_user.id).ia_default_ttl_hours == 24
    assert (
        after["Ip"] == before["Ip"]
        and after["InstantAccess"] == before["InstantAccess"]
    )
    assert after["Token"] == before["Token"]


@pytest.mark.parametrize("resource", ["ip", "link"])
@pytest.mark.parametrize("mode", ["standard", "custom"])
@pytest.mark.parametrize("hours", [1, 24, 720])
def test_valid_creation_ttl_preserves_exact_expiration(
    resource,
    mode,
    hours,
    client,
    login,
    user,
    db,
    app_modules,
    frozen_time,
):
    """Both paths accept the inclusive bounds and persist the requested duration."""
    login(client, user)
    path, fields, model_name = _resource(resource)
    ttl = (
        {"ttl_hours": str(hours), "custom_ttl_hours": "ignored"}
        if mode == "standard"
        else {
            "ttl_hours": "custom",
            "custom_ttl_hours": str(hours),
        }
    )
    response = client.post(path, data={"action": "create", **fields, **ttl})
    assert response.status_code == 200
    assert not response.context["language"].get("warning")
    db.expire_all()
    row = db.query(getattr(app_modules.models, model_name)).one()
    assert row.owner_id == user.id
    assert row.expires_at == frozen_time + timedelta(hours=hours)
    assert row.is_permanent is False


@pytest.mark.parametrize("resource", ["ip", "link"])
@pytest.mark.parametrize("ttl_field", [{}, {"ttl_hours": ""}])
def test_omitted_creation_ttl_uses_the_validated_account_default(
    resource,
    ttl_field,
    client,
    login,
    user,
    db,
    app_modules,
    frozen_time,
):
    """Omitted/empty standard TTL still uses that resource's account default."""
    user.ip_default_ttl_hours = 6
    user.ia_default_ttl_hours = 48
    db.commit()
    login(client, user)
    path, fields, model_name = _resource(resource)
    response = client.post(path, data={"action": "create", **fields, **ttl_field})
    assert response.status_code == 200
    row = db.query(getattr(app_modules.models, model_name)).one()
    assert row.expires_at == frozen_time + timedelta(
        hours=6 if resource == "ip" else 48
    )


@pytest.mark.parametrize("resource", ["ip", "link"])
@pytest.mark.parametrize("invalid_default", [0, 721])
def test_invalid_legacy_default_is_not_used_for_a_new_expiration(
    resource,
    invalid_default,
    client,
    login,
    user,
    db,
    app_modules,
    frozen_time,
):
    """Old stored defaults are not rewritten, but cannot bypass the new bound."""
    setattr(
        user,
        "ip_default_ttl_hours" if resource == "ip" else "ia_default_ttl_hours",
        invalid_default,
    )
    db.commit()
    login(client, user)
    path, fields, _ = _resource(resource)
    before = _snapshot(db, app_modules.models)
    response = client.post(path, data={"action": "create", **fields})
    _assert_invalid_duration(response)
    assert _snapshot(db, app_modules.models) == before


@pytest.mark.parametrize("resource", ["ip", "link"])
@pytest.mark.parametrize(
    "ttl",
    [
        {"ttl_hours": "721"},
        {"ttl_hours": "custom", "custom_ttl_hours": ""},
    ],
)
def test_permanent_resource_does_not_require_an_unused_ttl(
    resource,
    ttl,
    client,
    login,
    user,
    db,
    app_modules,
    frozen_time,
):
    """The permanence flag overrides expiry fields; there is no time to validate."""
    login(client, user)
    path, fields, model_name = _resource(resource)
    response = client.post(
        path, data={"action": "create", **fields, **ttl, "is_permanent": "true"}
    )
    assert response.status_code == 200
    assert not response.context["language"].get("warning")
    db.expire_all()
    row = db.query(getattr(app_modules.models, model_name)).one()
    assert row.is_permanent is True
    assert row.expires_at is None


@pytest.mark.parametrize("language", ["fr", "en"])
@pytest.mark.parametrize("resource", ["ip", "link", "account"])
def test_duration_refusal_explains_the_bounds_in_the_selected_language(
    language,
    resource,
    client,
    login,
    user,
    db,
    app_modules,
):
    """All three forms render the shared, localized inclusive range on refusal."""
    login(client, user)
    client.cookies.set("lang", language)
    if resource == "account":
        path, data = f"/users/details/{user.id}", {"ip_default_ttl_hours": "721"}
    else:
        path, fields, _ = _resource(resource)
        data = {"action": "create", **fields, "ttl_hours": "721"}
    before = _snapshot(db, app_modules.models)
    response = client.post(path, data=data)
    _assert_invalid_duration(response)
    message = response.context["language"]["warning"]
    assert "1" in message and "720" in message
    assert ("heures" if language == "fr" else "hours") in message
    if resource != "account":
        assert 'name="custom_ttl_hours" min="1" max="720"' in response.text
    assert _snapshot(db, app_modules.models) == before


@pytest.mark.parametrize("resource", ["ip", "link"])
def test_creation_page_exposes_the_server_ttl_maximum(resource, client, login, user):
    """Browser hints match the server limit on the initial page too."""
    login(client, user)
    path, _, _ = _resource(resource)
    response = client.get(path)
    assert response.status_code == 200
    assert 'name="custom_ttl_hours" min="1" max="720"' in response.text


@pytest.mark.parametrize("value", [True, False, None, 1.5])
def test_duration_parser_does_not_coerce_non_integer_values(value, app_modules):
    """Internal callers cannot turn booleans/floats into valid durations by coercion."""
    with pytest.raises(ValueError):
        app_modules.ttl.validate_ttl_hours(value)


@pytest.mark.parametrize(
    "value,expected", [(1, 1), (720, 720), (" 24 ", 24), ("+6", 6)]
)
def test_duration_parser_preserves_supported_whole_hour_inputs(
    value, expected, app_modules
):
    """Keep existing integer-form compatibility inside the approved range."""
    assert app_modules.ttl.MAX_TTL_HOURS == 720
    assert app_modules.ttl.validate_ttl_hours(value) == expected
