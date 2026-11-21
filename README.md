# MySafeIP

MySafeIP lets authorized users register their IP addresses for use by systems that maintain access allowlists. It does not configure a firewall by itself.

[Version française](README-FR.md)

## Run locally with Docker Compose

From a fresh checkout, with Docker, the Compose plugin, and OpenSSL installed:

```sh
(umask 077; set -C; printf 'JWT_SECRET=%s\n' "$(openssl rand -hex 32)" > .env)
docker compose up -d --build --wait
```

The first command refuses to overwrite an existing `.env`. Keep this file private and retain the same secret across restarts. Open `http://127.0.0.1:8000`. Signups are disabled by default. Create the first administrator interactively:

```sh
docker compose exec web python -c 'from getpass import getpass; from init_admin import main; raise SystemExit(main([input("Admin email: "), getpass("Password: ")]))'
```

Sign in with that account. The container listens on the host loopback interface only. To use another local port, set both `MYSAFEIP_PORT` and `MYSAFEIP_URL` in `.env` (for example `8080` and `http://127.0.0.1:8080`). Set `MYSAFEIP_LANGUAGE` to `en` or `fr`. Before exposing the app to a network, set up HTTPS and review your access policy.

SQLite data lives on the Compose `data` volume. `docker compose down` stops the app and preserves that volume; `docker compose down --volumes` deletes it. Back up the database before upgrades.

## Run the tests

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-test.txt
python scripts/smoke-runtime.py app
python -m pytest -q
```

## License

[Apache License 2.0](LICENSE) for the MySafeIP code. Bundled third-party files retain their respective licenses and copyright notices.
