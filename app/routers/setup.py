"""One-time web bootstrap of a new SQLite installation."""

from contextlib import contextmanager
from sqlite3 import SQLITE_BUSY, SQLITE_LOCKED
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

import crud
from auth import check_user_language, password_validity
from database import get_db
from models import InitialSetup, User
from schemas import UserCreate
from settings import settings

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory="templates")
PRIVATE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "same-origin"}
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


@contextmanager
def retry_on_busy(db: Session):
    try:
        yield
    except OperationalError as error:
        code = getattr(error.orig, "sqlite_errorcode", 0)
        if (code & 0xFF) not in (SQLITE_BUSY, SQLITE_LOCKED):
            raise
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Setup database is busy; try again.",
            headers={**PRIVATE_HEADERS, "Retry-After": "1"},
        ) from error


def is_available(db: Session) -> bool:
    if not settings.DISABLE_REGISTER:
        return False
    with retry_on_busy(db):
        return db.get(InitialSetup, 1) is not None and db.query(User.id).first() is None


def unavailable() -> Response:
    return Response(status_code=404, headers=PRIVATE_HEADERS)


def setup_host_allowed(request: Request) -> bool:
    try:
        host = request.url.hostname
        return host in LOCAL_HOSTS or (
            host is not None and host == urlsplit(settings.URL_WEBSITE).hostname
        )
    except ValueError:
        return False


def render_form(request: Request, language: dict, status: int = 200, error: str = ""):
    return templates.TemplateResponse(
        request,
        "setup.html",
        {"language": language, "error": error},
        status_code=status,
        headers=PRIVATE_HEADERS,
    )


@router.get("/setup")
def setup_form(
    request: Request,
    db: Session = Depends(get_db),
    language: dict = Depends(check_user_language),
):
    if not is_available(db):
        return unavailable()
    if not setup_host_allowed(request):
        return Response(status_code=403, headers=PRIVATE_HEADERS)
    return render_form(request, language)


@router.post("/setup")
def create_first_admin(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    confirm_password: str = Form(""),
    db: Session = Depends(get_db),
    language: dict = Depends(check_user_language),
):
    if not is_available(db):
        return unavailable()
    # Prevent other sites from submitting the local bootstrap form in a browser.
    origin = request.headers.get("origin")
    site = request.headers.get("sec-fetch-site")
    if not setup_host_allowed(request) or site not in (None, "same-origin"):
        return Response(status_code=403, headers=PRIVATE_HEADERS)
    if origin is None:
        same_origin = site == "same-origin"
    else:
        same_origin = origin == f"{request.url.scheme}://{request.url.netloc}"
    if not same_origin:
        return Response(status_code=403, headers=PRIVATE_HEADERS)
    if password != confirm_password or not password_validity(password):
        return render_form(request, language, 422, "Setup-invalid-password")
    try:
        admin = UserCreate(email=email, password=password, is_admin=True)
    except ValidationError:
        return render_form(request, language, 422, "Setup-invalid-email")

    # Release the read transaction, then acquire SQLite's writer lock before
    # rechecking eligibility. create_user consumes the marker in the same commit.
    db.rollback()
    with retry_on_busy(db):
        db.execute(text("BEGIN IMMEDIATE"))
        if not is_available(db):
            return unavailable()
        crud.create_user(db, admin)
    return RedirectResponse("/signin", status_code=303, headers=PRIVATE_HEADERS)
