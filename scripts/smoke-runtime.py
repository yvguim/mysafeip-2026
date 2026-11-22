"""Check real HTTP readiness and graceful scheduler shutdown under Uvicorn (Linux)."""

import argparse
import os
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
from http.client import HTTPConnection, HTTPException
from pathlib import Path

READINESS_TIMEOUT = 20
UVICORN = """
import logging
import socket
import sys
import uvicorn

logging.basicConfig(level=logging.INFO, format='%(name)s: %(message)s')
with socket.socket(fileno=int(sys.argv[1])) as listener:
    config = uvicorn.Config('main:app', lifespan='on', timeout_graceful_shutdown=5)
    uvicorn.Server(config).run(sockets=[listener])
"""


def wait_for_home(process: subprocess.Popen, port: int) -> None:
    """Check the rendered anonymous homepage over an actual loopback connection."""

    def deadline_expired(_signum, _frame):
        raise RuntimeError("Homepage did not respond before the readiness deadline")

    # Socket timeouts limit idle reads, not the total duration of a slow response.
    previous_handler = signal.signal(signal.SIGALRM, deadline_expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, READINESS_TIMEOUT)
        while True:
            if process.poll() is not None:
                raise RuntimeError(
                    f"Uvicorn exited before readiness ({process.returncode})"
                )
            connection = HTTPConnection("127.0.0.1", port, timeout=1)
            try:
                connection.request("GET", "/")
                with connection.getresponse() as response:
                    if (
                        response.status != 200
                        or b'href="/signin"' not in response.read()
                    ):
                        raise RuntimeError(
                            f"Unexpected homepage response (HTTP {response.status})"
                        )
                return
            except (OSError, HTTPException):
                time.sleep(0.1)
            finally:
                connection.close()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def run_smoke(app_dir: Path, scratch: Path) -> None:
    """Run the production app with only disposable configuration and storage."""
    environment = {
        "PATH": os.defpath,
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{scratch / 'smoke.sqlite'}",
        "JWT_SECRET": secrets.token_hex(48),
        "ALGORITHM": "HS256",
        "ACCESS_TOKEN_EXPIRE_MINUTES": "5",
        "URL_WEBSITE": "http://127.0.0.1",
        "DEFAULT_LANGUAGE": "en",
        "DISABLE_REGISTER": "false",
        "ADMIN_SEE_USERS_IP": "false",
        "TRUSTED_PROXIES": "false",
    }
    with (scratch / "uvicorn.log").open("w+", encoding="utf-8") as log:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            fd = listener.fileno()
            process = subprocess.Popen(
                [sys.executable, "-c", UVICORN, str(fd)],
                cwd=app_dir,
                env=environment,
                pass_fds=(fd,),
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        try:
            wait_for_home(process, port)
            process.send_signal(signal.SIGTERM)
            status = process.wait(timeout=10)
            log.seek(0)
            output = log.read()
            # Uvicorn can re-raise SIGTERM after a successful graceful shutdown.
            expected = (
                "apscheduler.scheduler: Scheduler started",
                "apscheduler.scheduler: Scheduler has been shut down",
                "Application shutdown complete.",
            )
            if status not in (0, -signal.SIGTERM) or any(
                marker not in output for marker in expected
            ):
                raise RuntimeError(
                    f"Scheduler or Uvicorn did not complete a graceful shutdown (status {status})"
                )
        except (RuntimeError, subprocess.TimeoutExpired):
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            log.seek(0)
            print(
                log.read().replace(environment["JWT_SECRET"], "[redacted]"),
                file=sys.stderr,
            )
            raise
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


def main() -> None:
    """Parse the application directory and execute the disposable probe."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "app_dir", type=Path, help="directory containing main.py and templates/"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="also report a successful check"
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="mysafeip-runtime-") as scratch:
        run_smoke(args.app_dir.resolve(strict=True), Path(scratch))
    if args.verbose:
        print(
            f"Python {sys.version.split()[0]}: GET / returned HTTP 200; APScheduler and Uvicorn shut down cleanly"
        )


if __name__ == "__main__":
    main()
