# MySafeIP

MySafeIP lets authorized users register their IP addresses for use by systems that maintain access allowlists. It does not configure a firewall by itself.

[Version française](README-FR.md)

## User documentation

- [Overview and features](docs/users/overview.md) — what MySafeIP does and what an external integration still needs to do.
- [Installation](docs/users/installation.md) — start with Docker Compose, create the first administrator, and preserve your data.
- [Usage](docs/users/usage.md) — manage IPs, share instant-access links, secure your account, and read the list from a script.

## Run the tests

```sh
python3.12 -m venv .venv
. .venv/bin/activate
sh scripts/quiet-check.sh python -m pip install -r requirements-test.txt
python scripts/smoke-runtime.py app
sh scripts/quiet-check.sh python -m pytest
```

These commands are silent on success. By default, pytest shows short tracebacks
and stops at the first failure. To see progress, omit `sh scripts/quiet-check.sh`;
to run the full suite even after a failure, pass `--maxfail=0` to pytest. To show
the smoke test's success message, pass `--verbose`.

## License

[Apache License 2.0](LICENSE) for the MySafeIP code. Bundled third-party files retain their respective licenses and copyright notices.
