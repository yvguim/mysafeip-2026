"""Host-side recovery script, streamed to Python via stdin in the container."""

import argparse
import sys
from pathlib import Path
from secrets import token_urlsafe
from urllib.parse import unquote, urlsplit


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="reset_admin", description="Reset an active MySafeIP administrator."
    )
    parser.add_argument("email", help="exact email address of the administrator")
    args = parser.parse_args()

    from sqlalchemy import update
    from sqlalchemy.exc import SQLAlchemyError

    from database import SessionLocal, engine
    from models import User
    from security import get_password_hash

    # Do not let SQLite create a new file if the configured volume is missing.
    if engine.dialect.name == "sqlite":
        (filename,), options = engine.dialect.create_connect_args(engine.url)
        if options.get("uri") and filename.startswith("file:"):
            filename = unquote(urlsplit(filename).path)
        if not filename or not Path(filename).is_file():
            print("MySafeIP database not found.", file=sys.stderr)
            return 1

    # The fixed prefix guarantees the app's character requirements; the rest is random.
    password = "Aa0!" + token_urlsafe(24)
    try:
        with SessionLocal() as db:
            result = db.execute(
                update(User)
                .where(
                    User.email == args.email,
                    User.is_admin.is_(True),
                    User.is_active.is_(True),
                )
                .values(hashed_password=get_password_hash(password), twofactor="")
            )
            if result.rowcount != 1:
                print("No active administrator matches that email.", file=sys.stderr)
                return 1
            db.commit()
    except SQLAlchemyError:
        print(
            "Unable to reset the administrator in the MySafeIP database.",
            file=sys.stderr,
        )
        return 1

    print(password)
    return 0


if __name__ == "__main__":
    sys.exit(main())
