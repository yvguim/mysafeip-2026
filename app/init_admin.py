import sys

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

import crud
from database import SessionLocal
from schemas import UserCreate


class EmailAlreadyRegisteredError(Exception):
    """The requested admin email is already registered."""


def create_user(email, password, db):
    user = UserCreate(email=email, is_admin=True, is_active=True, password=password)
    if crud.get_user_by_email(db, email=user.email):
        raise EmailAlreadyRegisteredError("Email already registered")
    return crud.create_user(db, user)


def main(argv: list[str]) -> int:
    """Create an admin account from two command-line arguments."""
    if len(argv) != 2:
        print(
            "Usage: python init_admin.py yourmail@example.com your_password",
            file=sys.stderr,
        )
        return 2
    try:
        with SessionLocal() as db:
            create_user(email=argv[0], password=argv[1], db=db)
    except EmailAlreadyRegisteredError as error:
        print(error, file=sys.stderr)
        return 1
    except (ValidationError, ValueError):
        print("Invalid email or password", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("Unable to create admin account in the database", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
