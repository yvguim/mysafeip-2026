"""
Main MySafeIP API pages
"""

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import crud
import models
from auth import check_user, check_user_language, get_current_user
from database import SessionLocal, engine, get_db, initialize_database
from routers import auth, instant_access, ips, setup, users
from security import get_client_ip

initialize_database(engine)

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

app.include_router(users.router)
app.include_router(ips.router)
app.include_router(instant_access.router)
app.include_router(auth.router)
app.include_router(setup.router)


app.mount("/static", StaticFiles(directory="templates/static"), name="static")
templates = Jinja2Templates(directory="templates")


def cleanup_expired_ips():
    with SessionLocal() as db:
        count = crud.delete_expired_ips(db)
        if count > 0:
            print(f"[scheduler] Deleted {count} expired IPs")


def cleanup_expired_links():
    with SessionLocal() as db:
        count = crud.delete_expired_links(db)
        if count > 0:
            print(f"[scheduler] Deleted {count} expired instant links")


scheduler = BackgroundScheduler()
scheduler.add_job(func=cleanup_expired_ips, trigger="interval", minutes=1)
scheduler.add_job(func=cleanup_expired_links, trigger="interval", minutes=1)
scheduler.start()


@app.on_event("shutdown")
def shutdown_scheduler():
    scheduler.shutdown()


@app.get("/docs")
async def get_documentation(current_user: models.User = Depends(get_current_user)):
    """Force authentication for doc page"""
    if current_user.is_admin:
        return get_swagger_ui_html(openapi_url="/openapi.json", title="docs")
    raise HTTPException(status_code=401, detail="Only admins can use fastapi docs")


@app.get("/openapi.json")
async def openapi(current_user: models.User = Depends(get_current_user)):
    """Force authentication for openapi page"""
    if current_user.is_admin:
        return get_openapi(title="FastAPI", version="0.1.0", routes=app.routes)
    raise HTTPException(status_code=401, detail="Only admins can use openapi.json")


@app.get("/")
async def main(
    request: Request,
    db: Session = Depends(get_db),
    language: dict = Depends(check_user_language),
):
    """Home page get request"""
    if setup.is_available(db):
        return RedirectResponse(
            "/setup", status_code=303, headers=setup.PRIVATE_HEADERS
        )
    client_host = get_client_ip(request)
    user = await check_user(request, db)
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "request": request,
            "client_host": client_host,
            "user": user,
            "language": language,
        },
    )


@app.get("/lang/{lang}", name="main")
async def set_language(
    request: Request,
    lang: str,
    db: Session = Depends(get_db),
    language: dict = Depends(check_user_language),
):
    """Home page get request"""
    client_host = get_client_ip(request)
    user = await check_user(request, db)
    response = templates.TemplateResponse(
        request,
        "home.html",
        {
            "request": request,
            "client_host": client_host,
            "user": user,
            "language": language,
        },
    )
    response.set_cookie(key="lang", value=lang, httponly=True, samesite="lax")
    return response
