# Install with Docker Compose

[Index](../../README.md) · [Overview](overview.md) · [Usage](usage.md) · [Français](../utilisateurs/installation.md)

## Start a local instance

You need Docker Engine 28.0.0 or newer and the Docker Compose plugin. Older Docker Engine versions can expose loopback-published ports to other hosts on the local network. From the repository root, next to `compose.yaml`, run the commands below. Compose pulls the public `yvguim/mysafeip` image from Docker Hub without a local build. See `env.template` for available settings.

Use a released tag that supports both tokenless setup and an optional `JWT_SECRET`. The default tag must be published before these commands can work; earlier images are not compatible with this first-run guide.

```sh
docker compose up -d --wait
docker compose ps
```

No `.env` is required for startup. If `JWT_SECRET` is missing or blank, MySafeIP generates a new signing secret at each startup and logs a warning without revealing it. Existing login sessions become invalid after a restart; accounts and data are unaffected. To keep sessions across restarts, generate a private value with `openssl rand -hex 32`, set `JWT_SECRET` in `.env`, and run `docker compose up -d --wait`. Keep that value private and unchanged. At startup, MySafeIP also creates the SQLite file and tables if they are missing.

For a custom deployment with multiple workers or replicas, set the same `JWT_SECRET` on all of them so sessions work regardless of which process handles the request.

```text
Browser ── HTTP on 127.0.0.1:8000 ──> Web container
                                            │ reads and writes
                                            ▼
                                     Compose data volume
                                        /data/mysafeip.db
```

## Create the first administrator

**Do not expose the instance to the network, even through a reverse proxy, until the first administrator exists.** Anyone who can reach the setup page can create the account. This also applies to installations where initial setup was interrupted.

1. Open `http://127.0.0.1:8000`. On a fresh install, MySafeIP shows the form for creating the first administrator.
2. Provide your email address and choose a unique password. No setup token is needed.
3. Submit the form, then sign in. The form closes permanently for this database, even after a restart.

The form is only available for databases awaiting initial setup. Regular signups remain closed. Enable TOTP in your profile; see [Usage](usage.md).

Use `localhost`, `127.0.0.1` or the host configured in `MYSAFEIP_URL`. If you use a private reverse proxy for setup, preserve the browser-facing `Host` (including the port) and set `X-Forwarded-Proto` to the original scheme.

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

The port binds to the host loopback interface. Links generated with `127.0.0.1` won't work for remote recipients. By default, proxy headers are accepted only from the **container's** loopback interface. If your proxy runs on the host or in another container, set `MYSAFEIP_FORWARDED_ALLOW_IPS` to its address as seen by MySafeIP. Set an empty value to disable trust. Before exposing the app, configure HTTPS, block direct access, and require the proxy to overwrite client-supplied forwarding headers.

## Stop, back up, and upgrade

- `docker compose stop` stops the service; `docker compose up -d --wait` starts it again.
- `docker compose down` removes the containers and preserves the SQLite volume. **`docker compose down --volumes` deletes the data.** Don't use it for an upgrade.
- Before upgrading, stop the service and make a consistent SQLite backup; keep `.env` and the backup separately in private storage. Test restoration on a copy before touching real data.
- Select a published version, set `MYSAFEIP_IMAGE_TAG` in `.env`, then run `docker compose pull` and `docker compose up -d --wait`. Keep the same Compose project and volume. Don't assume an old database is migrated automatically.

## Troubleshoot startup

- `docker compose config -q` checks the configuration without displaying any configured secret.
- `docker compose ps` shows service state. `docker compose logs --tail=100 web` helps identify errors. Review logs before sharing them; they may contain sensitive information.
- If the home page is unreachable after changing the port, open the new address and confirm the port isn't already in use. For SQLite permission errors, check that container user `10001` can write to the volume; don't work around the issue by running the application as root.
