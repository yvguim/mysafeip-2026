"""Historical #8 reproductions promoted to ordinary regression tests."""

import pyotp
import pytest

from tests.test_password_policy import _snapshot

pytestmark = pytest.mark.characterization


@pytest.mark.parametrize("operation", ["ttl-update", "token-generation"])
def test_unrelated_account_update_preserves_enabled_totp(
    operation, app_modules, db, user, client, client_factory, login, password, totp_time
):
    """A successful TTL/token update must not implicitly disable existing 2FA."""
    secret = pyotp.random_base32()
    user.twofactor = secret
    db.commit()
    assert pyotp.TOTP(user.twofactor).verify(
        pyotp.TOTP(secret).at(totp_time), for_time=totp_time
    )
    login(client, user, two_factor_code=pyotp.TOTP(secret).now())
    before = _snapshot(db, app_modules.models)
    data = (
        {"ip_default_ttl_hours": "6", "ia_default_ttl_hours": "48"}
        if operation == "ttl-update"
        else {"token": "true", "description": "generated safely"}
    )
    response = client.post(f"/users/details/{user.id}", data=data)
    assert response.status_code == 200
    after = _snapshot(db, app_modules.models)
    if operation == "ttl-update":
        assert user.ip_default_ttl_hours == 6 and user.ia_default_ttl_hours == 48
        assert after["Token"] == before["Token"]
    else:
        assert len(after["Token"]) == len(before["Token"]) + 1
        assert db.query(app_modules.models.Token).one().owner_id == user.id
    fresh = client_factory()
    without_code = fresh.post(
        "/signin", data={"username": user.email, "password": password}
    )
    assert without_code.status_code == 200
    assert user.twofactor == secret
    assert "access_token" not in fresh.cookies
