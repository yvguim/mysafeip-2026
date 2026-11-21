import pyotp
from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

import crud
import schemas
from auth import (
    authenticate,
    authenticate_by_key,
    check_user,
    check_user_language,
    create_access_token,
    password_validity,
)
from database import get_db
from security import get_client_ip
from settings import settings

router = APIRouter(prefix="", tags=["auth"], dependencies=[Depends(get_db)])
router.mount("/static", StaticFiles(directory="templates/static"), name="static")
templates = Jinja2Templates(directory="templates")


def render(request: Request, template: str, context: dict):
    return templates.TemplateResponse(request, template, context)


@router.get("/register")
async def register(
    request: Request, db=Depends(get_db), language=Depends(check_user_language)
):
    if settings.DISABLE_REGISTER:
        language["warning"] = language["Registering-disabled"]
    user = await check_user(request, db)
    return render(
        request,
        "register.html",
        {"request": request, "user": user, "language": language},
    )


@router.post("/register")
async def post_register(
    request: Request,
    email=Form(),
    password=Form(),
    confirm_password=Form(),
    db=Depends(get_db),
    language=Depends(check_user_language),
):
    user = await check_user(request, db)
    ctx = {
        "request": request,
        "client_host": get_client_ip(request),
        "user": user,
        "language": language,
    }

    if settings.DISABLE_REGISTER or user or crud.get_user_by_email(db, email):
        language["warning"] = language["Account-creation-error"]
        return render(request, "register.html", ctx)

    if not password_validity(password) or confirm_password != password:
        language["warning"] = language.get(
            "Password-help" if not password_validity(password) else "Password-missmatch"
        )
        return render(
            request,
            "register.html",
            ctx | {"email": email} if not password_validity(password) else ctx,
        )

    try:
        new_user = schemas.UserCreate(email=email, is_admin=False, password=password)
    except ValidationError:
        language["danger"] = language["Account-creation-error"]
        return render(request, "register.html", ctx)

    user = crud.create_user(db=db, user=new_user)
    if not user:
        language["danger"] = language["Account-creation-error"]
        return render(request, "register.html", ctx)

    language["success"] = language["Account-creation-successfull"]
    access_token = create_access_token(sub=user.id)
    response = render(request, "register.html", ctx | {"user": user})
    response.set_cookie(
        key="access_token",
        value=f"Bearer {jsonable_encoder(access_token)}",
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/signin")
async def get_signin(
    request: Request, db=Depends(get_db), language=Depends(check_user_language)
):
    user = await check_user(request, db)
    return render(
        request, "signin.html", {"request": request, "user": user, "language": language}
    )


@router.post("/signin")
async def post_signin(
    response: Response,
    request: Request,
    db=Depends(get_db),
    language=Depends(check_user_language),
    two_factor_code=Form(""),
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    ctx = {
        "request": request,
        "client_host": get_client_ip(request),
        "language": language,
    }
    user = authenticate(email=form_data.username, password=form_data.password, db=db)

    if not user:
        language["warning"] = language["Incorrect-username-or-password"]
        return render(request, "signin.html", ctx | {"user": None})

    if user.twofactor:
        try:
            totp = pyotp.TOTP(user.twofactor)
        except ValueError:
            # A legacy secret rejected by PyOTP must not disable the second factor.
            totp = None
        if totp is None or not totp.verify(two_factor_code):
            language["warning"] = language["Incorrect-totp"]
            return render(request, "signin.html", ctx | {"user": None})

    for scope in form_data.scopes:
        if scope == "cli":
            return {"access_token": create_access_token(sub=user.id)}

    language["success"] = language["Signin-success"]
    response = render(request, "signin.html", ctx | {"user": user})
    response.set_cookie(
        key="access_token",
        value=f"Bearer {jsonable_encoder(create_access_token(sub=user.id))}",
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/token-signin")
async def post_token_signin(db=Depends(get_db), key=Form(""), secret=Form("")):
    user = authenticate_by_key(key=key, secret=secret, db=db)
    if not user:
        return {"Auth": "Error"}
    return {"access_token": create_access_token(sub=user.id)}


@router.get("/logout")
async def logout(
    response: Response, request: Request, language=Depends(check_user_language)
):
    language["success"] = language["Logout-successfull"]
    response = render(
        request,
        "home.html",
        {
            "request": request,
            "client_host": get_client_ip(request),
            "user": "",
            "language": language,
        },
    )
    response.delete_cookie(key="access_token")
    return response
