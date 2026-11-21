"""Dependency regressions and real HTTP form compatibility for issue #42."""

import pytest


@pytest.mark.parametrize("parser_kind", ["multipart", "querystring"])
def test_default_parser_callbacks_do_not_leak_between_instances(parser_kind):
    """A callback registered on one parser must not process another request."""
    from python_multipart import MultipartParser, QuerystringParser

    if parser_kind == "multipart":
        first = MultipartParser("boundary")
        second = MultipartParser("boundary")
        event = "part_begin"
        body = b'--boundary\r\nContent-Disposition: form-data; name="value"\r\n\r\nok\r\n--boundary--\r\n'
    else:
        first = QuerystringParser()
        second = QuerystringParser()
        event = "field_start"
        body = b"value=ok"
    called = []
    first.set_callback(event, lambda: called.append(True))
    try:
        second.write(body)
        second.finalize()
        assert called == [], "A callback leaked from a different parser instance"
        first.write(body)
        first.finalize()
        assert called == [True], "The originating parser must retain its callback"
    finally:
        # Also clean the shared dictionary on old versions during RED verification.
        first.set_callback(event, None)


@pytest.mark.parametrize("encoding", ["urlencoded", "multipart"])
@pytest.mark.parametrize("cli", [False, True])
def test_signin_form_encodings_preserve_authentication(
    client, user, password, encoding, cli
):
    """Both form encodings preserve real cookie and CLI/Bearer authentication."""
    fields = {"username": user.email, "password": password}
    if cli:
        fields["scope"] = "cli"
    kwargs = (
        {"data": fields}
        if encoding == "urlencoded"
        else {"files": {name: (None, value) for name, value in fields.items()}}
    )
    response = client.post("/signin", **kwargs)
    assert response.status_code == 200
    if cli:
        payload = response.json()
        assert set(payload) == {"access_token"}
        assert isinstance(payload["access_token"], str)
        assert "access_token" not in client.cookies
        headers = {"Authorization": f"Bearer {payload['access_token']}", "Cli": "true"}
    else:
        assert "access_token" in client.cookies
        headers = {"Cli": "true"}
    exported = client.get("/ips/config/", headers=headers)
    assert exported.status_code == 200
    assert exported.json() == []


@pytest.mark.parametrize("encoding", ["urlencoded", "multipart"])
def test_invalid_signin_form_encodings_do_not_issue_session(client, user, encoding):
    """Changing encodings cannot turn invalid credentials into a valid session."""
    fields = {
        "username": user.email,
        "password": "Invalid-test-password-42!",
        "scope": "cli",
    }
    kwargs = (
        {"data": fields}
        if encoding == "urlencoded"
        else {"files": {name: (None, value) for name, value in fields.items()}}
    )
    response = client.post("/signin", **kwargs)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "access_token" not in client.cookies
    assert client.get("/ips/config/").status_code == 401
