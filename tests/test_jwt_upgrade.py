"""PyJWT #39 regressions using ephemeral keys and the existing HTTP contract."""

from datetime import UTC, datetime, timedelta

import pytest


def _snapshot(db, models):
    """Read all persisted synthetic fields without relying on cached ORM rows."""
    db.expire_all()
    return {
        model.__name__: [
            tuple(getattr(row, column.name) for column in model.__table__.columns)
            for row in db.query(model).order_by(model.id).all()
        ]
        for model in (models.User, models.Ip, models.InstantAccess, models.Token)
    }


def _claims(user):
    """Create a valid claim set before varying one invalid input."""
    now = datetime.now(UTC)
    return {
        "sub": str(user.id),
        "type": "access_token",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }


def _request_with_token(client, token, channel):
    """Exercise cookie and header extraction independently."""
    if channel == "cookie":
        client.cookies.set("access_token", f"Bearer {token}")
        return client.get("/ips/config/", headers={"Cli": "true"})
    return client.get(
        "/ips/config/", headers={"Authorization": f"Bearer {token}", "Cli": "true"}
    )


def _assert_refusal(response):
    """Preserve the established invalid-JWT response, without following logout."""
    assert response.status_code == 302
    assert response.headers["location"] == "/logout"
    assert response.headers["set-cookie"] == "access_token=deleted"
    assert response.json() == {"detail": "Could not validate credentials"}


@pytest.mark.parametrize("channel", ["cookie", "bearer"])
@pytest.mark.parametrize("claim", ["exp", "nbf", "iat"])
@pytest.mark.parametrize("value", [None, [], {}], ids=["null", "list", "object"])
def test_invalid_numeric_date_is_refused_without_server_error(
    client,
    user,
    db,
    app_modules,
    channel,
    claim,
    value,
):
    """Signed malformed date claims must reach the normal refusal, not TypeError."""
    auth = app_modules.auth
    claims = {**_claims(user), claim: value}
    token = auth.jwt.encode(
        claims, auth.settings.JWT_SECRET, algorithm=auth.settings.ALGORITHM
    )
    before = _snapshot(db, app_modules.models)
    _assert_refusal(_request_with_token(client, token, channel))
    assert _snapshot(db, app_modules.models) == before


@pytest.mark.parametrize("channel", ["cookie", "bearer"])
@pytest.mark.parametrize("algorithm", ["none", "HS384"])
def test_unapproved_jwt_algorithm_remains_refused(
    client,
    user,
    db,
    app_modules,
    channel,
    algorithm,
):
    """The token header must not override the configured HS256 allow-list."""
    auth = app_modules.auth
    assert auth.settings.ALGORITHM == "HS256"
    key = None if algorithm == "none" else auth.settings.JWT_SECRET
    token = auth.jwt.encode(_claims(user), key, algorithm=algorithm)
    before = _snapshot(db, app_modules.models)
    _assert_refusal(_request_with_token(client, token, channel))
    assert _snapshot(db, app_modules.models) == before
