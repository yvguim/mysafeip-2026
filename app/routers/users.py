import pyotp
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import crud
import models
import schemas
from auth import check_user_language, get_current_user, password_validity
from database import get_db
from security import verify_password
from ttl import validate_ttl_hours

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(get_db)])
router.mount("/static", StaticFiles(directory="templates/static"), name="static")
templates = Jinja2Templates(directory="templates")


@router.get("/read")
async def read_users(
    request: Request,
    db: Session = Depends(get_db),
    language: dict = Depends(check_user_language),
    current_user: models.User = Depends(get_current_user),
):
    user = current_user
    if current_user.is_admin:
        users = crud.get_users(db)
    else:
        users = []
        language["warning"] = language["Only-admin-can-get-users"]
    return templates.TemplateResponse(
        request,
        "users.html",
        {"request": request, "users": users, "user": user, "language": language},
    )


@router.post("/read")
async def delete_users(
    request: Request,
    db: Session = Depends(get_db),
    language: dict = Depends(check_user_language),
    email: str = Form(),
    current_user: models.User = Depends(get_current_user),
):
    user = current_user
    users = ""
    if (not user.is_admin) and (user.email != email):
        language["warning"] = language["Only-admin-can-delete-other-users"]
        return templates.TemplateResponse(
            request,
            "users.html",
            {"request": request, "users": "", "user": user, "language": language},
        )

    if (user.is_admin) and (user.email == email):
        language["warning"] = language["You cant delete your own admin account"]
        users = crud.get_users(db)
        return templates.TemplateResponse(
            request,
            "users.html",
            {"request": request, "users": users, "user": user, "language": language},
        )

    if crud.delete_user(db, email):
        language["success"] = (
            language["User"] + " " + email + language["deleted-successfully"]
        )
    else:
        language["warning"] = language["An-error-occured-while-deleting"] + email

    if user.is_admin:
        users = crud.get_users(db)
    else:
        response = RedirectResponse("/", status_code=302)
        response.delete_cookie(key="access_token")
        return response
    return templates.TemplateResponse(
        request,
        "users.html",
        {"request": request, "users": users, "user": user, "language": language},
    )


def _render_password_form(request, language, user, *, is_own_profile=False):
    return templates.TemplateResponse(
        request,
        "reset_password.html",
        {"user": user, "language": language, "is_own_profile": is_own_profile},
        headers={"Cache-Control": "no-store"},
    )


@router.get("/reset_password/{user_id}")
async def reset_password(
    user_id: int,
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    language: dict = Depends(check_user_language),
):
    if not current_user.is_admin and (current_user.id != user_id):
        language["danger"] = language["You-are-not-allowed-to-do-this"]
        return _render_password_form(request, language, False)
    is_own_profile = current_user.id == user_id
    user = current_user if is_own_profile else crud.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    return _render_password_form(request, language, user, is_own_profile=is_own_profile)


@router.post("/reset_password/{user_id}")
def post_reset_password(
    user_id: int,
    request: Request,
    current_user: models.User = Depends(get_current_user),
    password: str = Form(),
    confirm_password: str = Form(),
    current_password: str = Form(""),
    db: Session = Depends(get_db),
    language: dict = Depends(check_user_language),
):
    if not current_user.is_admin and (current_user.id != user_id):
        language["danger"] = language["You-are-not-allowed-to-do-this"]
        return _render_password_form(request, language, False)

    is_own_profile = current_user.id == user_id
    user = current_user if is_own_profile else crud.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    if is_own_profile and (
        not current_password
        or not verify_password(current_password, user.hashed_password)
    ):
        language["warning"] = language["Incorrect-current-password"]
    elif not password_validity(password):
        language["warning"] = language["Password-help"]
    elif confirm_password != password:
        language["warning"] = language["Password-missmatch"]
    elif not crud.reset_user_password(db=db, user=user, password=password):
        language["danger"] = language["An-error-occured-during-password-reset"]
    else:
        language["success"] = language["Password-reset-successfull"]
    return _render_password_form(request, language, user, is_own_profile=is_own_profile)


@router.get("/details/{user_id}", response_model=schemas.User)
async def user_details(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    language: dict = Depends(check_user_language),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.is_admin:
        user = crud.get_user(db, user_id=user_id)
    else:
        user = current_user
    if user is None:
        language["warning"] = language["User-does-not-exist"]
        user = None
    tokens = crud.get_tokens(db, user)
    return templates.TemplateResponse(
        request,
        "user-details.html",
        {
            "request": request,
            "user": user,
            "tokens": tokens,
            "language": language,
            "is_own_profile": user is not None and user.id == current_user.id,
        },
    )


@router.post("/details/{user_id}", name="user_details")
async def update_user_details(
    user_id: int,
    request: Request,
    twofactor: str = Form(""),
    twofactor_settings: str = Form(""),
    token: str = Form(""),
    action: str = Form(""),
    token_id=Form(""),
    description: str = Form(""),
    ip_default_ttl_hours: str = Form(""),
    ia_default_ttl_hours: str = Form(""),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    language: dict = Depends(check_user_language),
):
    twofactorurl = ""
    newtoken = ""
    if current_user.is_admin:
        user = crud.get_user(db, user_id=user_id)
    else:
        user = current_user

    if action == "delete" and (user is None or user.id != current_user.id):
        raise HTTPException(status_code=404, detail="Resource not found")

    # Validate all supplied TTLs before any token, TOTP or account mutation.
    try:
        ip_ttl = (
            validate_ttl_hours(ip_default_ttl_hours) if ip_default_ttl_hours else None
        )
        ia_ttl = (
            validate_ttl_hours(ia_default_ttl_hours) if ia_default_ttl_hours else None
        )
    except ValueError:
        language["warning"] = language["Invalid-duration"]
        tokens = crud.get_tokens(db, user) if user is not None else []
        return templates.TemplateResponse(
            request,
            "user-details.html",
            {
                "request": request,
                "user": user,
                "tokens": tokens,
                "language": language,
                "is_own_profile": user is not None and user.id == current_user.id,
                "twofactorurl": "",
                "newtoken": "",
            },
        )

    if action == "delete":
        if not crud.delete_token(db, token_id, owner_id=current_user.id):
            raise HTTPException(status_code=404, detail="Resource not found")
        language["success"] = language["Instant-link-deleted-successfully"]

    if token:
        newtoken = crud.create_new_token(db, user.id, description)

    # The settings marker distinguishes an unchecked checkbox from a partial POST.
    if action != "delete":
        if twofactor == "true" and user.twofactor == "":
            crud.enable_user_twofactor(db, user)
            twofactorurl = pyotp.totp.TOTP(user.twofactor).provisioning_uri(
                name=user.email, issuer_name="MySafeIP"
            )
        elif twofactor_settings == "true" and twofactor == "" and user.twofactor != "":
            crud.disable_user_twofactor(db, user)

    if ip_ttl is not None or ia_ttl is not None:
        crud.update_user_ttl(
            db,
            user,
            ip_ttl if ip_ttl is not None else user.ip_default_ttl_hours,
            ia_ttl,
        )

    tokens = crud.get_tokens(db, user)
    return templates.TemplateResponse(
        request,
        "user-details.html",
        {
            "request": request,
            "user": user,
            "twofactorurl": twofactorurl,
            "newtoken": newtoken,
            "tokens": tokens,
            "language": language,
            "is_own_profile": user.id == current_user.id,
        },
    )
