# Install with Docker Compose

[Index](../../README.md) · [Overview](overview.md) · [Usage](usage.md) · [Français](../utilisateurs/installation.md)

## Start a local instance

You need a running Docker engine, the Docker Compose plugin, and OpenSSL. From the repository root, next to `compose.yaml`, run the commands below. Compose builds the app from the supplied `Dockerfile`; a published MySafeIP image or registry credentials are not required for a standard installation.

```sh
(umask 077; set -C; jwt=$(openssl rand -hex 32) && setup=$(openssl rand -hex 32) &&
  printf 'JWT_SECRET=%s\nSETUP_TOKEN=%s\n' "$jwt" "$setup" > .env)
docker compose up -d --build --wait
docker compose ps
```

The first command refuses to overwrite an existing `.env`. If you've already configured the instance, keep the file and skip to startup. Don't share `.env`: it contains the session signing secret and, for a fresh install, the setup token. At startup, MySafeIP creates the SQLite file and tables if they are missing.

```text
Browser ── HTTP on 127.0.0.1:8000 ──> Web container
                                            │ reads and writes
                                            ▼
                                     Compose data volume
                                        /data/mysafeip.db
```

## Create the first administrator

1. Open `http://127.0.0.1:8000`. On a fresh install, MySafeIP shows the form for creating the first administrator.
2. Paste the `SETUP_TOKEN` value from `.env` into the form. Don't enter `JWT_SECRET`. Provide your email address and choose a unique password.
3. Submit the form, then sign in. The form closes permanently for this database, even after a restart. You can remove `SETUP_TOKEN` from `.env` and run `docker compose up -d --wait` to remove it from the container environment. Keep `JWT_SECRET`.

The form does not activate for an existing, initialized database or without a valid setup token distinct from `JWT_SECRET`. Regular signups remain closed. Keep the service local while setting it up, and enable TOTP in your profile; see [Usage](usage.md).

If you need to create an administrator without the form (for example on an existing database), run the following in an interactive terminal. The password isn't displayed or passed as a process argument.

```sh
docker compose exec web python -c 'from getpass import getpass; from init_admin import main; raise SystemExit(main([input("Admin email: "), getpass("Password: ")]))'
```

If the email already exists, the script does not replace the account.

## Configure the port, address, and language

If port 8000 is already in use, add these lines to `.env` without replacing `JWT_SECRET`, then run `docker compose up -d --wait` again:

```dotenv
MYSAFEIP_PORT=8080
MYSAFEIP_URL=http://127.0.0.1:8080
MYSAFEIP_LANGUAGE=en
```

`MYSAFEIP_PORT` sets the host port; `MYSAFEIP_URL` is the address used to generate links. Both must match your installation. The default language can be `en` or `fr`.

The port binds to the host loopback interface. Links generated with `127.0.0.1` won't work for remote recipients. Before exposing the app, configure HTTPS and review who can reach the instance. The supplied configuration does not trust proxy headers. If you adapt that setting, block direct access and require the proxy to replace client-supplied IP headers.

## Stop, back up, and upgrade

- `docker compose stop` stops the service; `docker compose up -d --wait` starts it again.
- `docker compose down` removes the containers and preserves the SQLite volume. **`docker compose down --volumes` deletes the data.** Don't use it for an upgrade.
- Before upgrading, stop the service and make a consistent SQLite backup; keep `.env` and the backup separately in private storage. Test restoration on a copy before touching real data.
- After selecting and obtaining the desired revision, rebuild with `docker compose up -d --build --wait`. Keep the same Compose project and volume. Don't assume an old database is migrated automatically.

## Troubleshoot startup

- `docker compose config -q` checks the configuration without displaying the secret. If `JWT_SECRET` is missing, check `.env`.
- `docker compose ps` shows service state. `docker compose logs --tail=100 web` helps identify errors. Review logs before sharing them; they may contain sensitive information.
- If the home page is unreachable after changing the port, open the new address and confirm the port isn't already in use. For SQLite permission errors, check that container user `10001` can write to the volume; don't work around the issue by running the application as root.
