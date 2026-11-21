from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import crud
import models
from auth import check_user, check_user_language, get_current_user
from database import get_db
from security import get_client_ip, is_valid_url
from settings import settings
from ttl import MAX_TTL_HOURS, validate_ttl_hours

router = APIRouter(
    prefix="/instant-access", tags=["instant-access"], dependencies=[Depends(get_db)]
)
router.mount("/static", StaticFiles(directory="templates/static"), name="static")
templates = Jinja2Templates(directory="templates")


def render(request: Request, template: str, context: dict):
    return templates.TemplateResponse(
        request, template, context | {"max_ttl_hours": MAX_TTL_HOURS}
    )


@router.get("/config/")
async def get_create_instant_access(
    request: Request,
    db=Depends(get_db),
    language=Depends(check_user_language),
    current_user: models.User = Depends(get_current_user),
):
    links = crud.get_links(db, user=current_user)
    return render(
        request,
        "instant_access.html",
        {
            "request": request,
            "user": current_user,
            "link": "https://your_secure_url",
            "url_website": settings.URL_WEBSITE,
            "links": links,
            "language": language,
            "default_ia_ttl": current_user.ia_default_ttl_hours,
        },
    )


@router.post("/config/")
async def post_instant_access(
    request: Request,
    link=Form(""),
    description=Form(""),
    action=Form(""),
    link_id=Form(""),
    ttl_hours=Form(""),
    is_permanent=Form(""),
    custom_ttl_hours=Form(""),
    db=Depends(get_db),
    language=Depends(check_user_language),
    current_user: models.User = Depends(get_current_user),
):
    ctx = {
        "request": request,
        "user": current_user,
        "language": language,
        "link": "https://destination_url",
        "url_website": settings.URL_WEBSITE,
    }

    if action == "delete":
        if not crud.delete_link(db, link_id, owner_id=current_user.id):
            raise HTTPException(status_code=404, detail="Resource not found")
        language["success"] = language["Instant-link-deleted-successfully"]

    if action == "create":
        if not link:
            link = "https://destination_url"

        if not is_valid_url(link):
            language["warning"] = language["Invalid-URL"]
            return render(
                request,
                "instant_access.html",
                ctx
                | {
                    "links": crud.get_links(db, user=current_user),
                    "default_ia_ttl": current_user.ia_default_ttl_hours,
                },
            )

        permanent = is_permanent == "true"
        try:
            selected_ttl = (
                custom_ttl_hours
                if ttl_hours == "custom"
                else ttl_hours or current_user.ia_default_ttl_hours
            )
            ttl = None if permanent else validate_ttl_hours(selected_ttl)
        except ValueError:
            language["warning"] = language["Invalid-duration"]
            return render(
                request,
                "instant_access.html",
                ctx
                | {
                    "links": crud.get_links(db, user=current_user),
                    "default_ia_ttl": current_user.ia_default_ttl_hours,
                },
            )

        link_created = crud.create_instant_access(
            db=db,
            link=link,
            user_id=current_user.id,
            description=description,
            ttl_hours=ttl,
            is_permanent=permanent,
        )
        if link_created:
            language["success"] = (
                str(link_created.link)
                + language["is-now-accessible-directly-from"]
                + str(link_created.unique_link)
            )

    return render(
        request,
        "instant_access.html",
        ctx
        | {
            "links": crud.get_links(db, user=current_user),
            "default_ia_ttl": current_user.ia_default_ttl_hours,
        },
    )


@router.get("/ia/{unique_link}")
async def get_link_redirect(
    request: Request,
    unique_link: str,
    db=Depends(get_db),
    language=Depends(check_user_language),
):
    client_host = get_client_ip(request)
    destination_link = crud.get_link_by_unique_link(db, unique_link=unique_link)

    if not destination_link:
        language["warning"] = language["Sorry-this-link-does-not-exists"]
        client_host = get_client_ip(request)
        user = await check_user(request, db)
        return render(
            request,
            "home.html",
            {
                "request": request,
                "client_host": client_host,
                "user": user,
                "language": language,
            },
        )

    if (
        destination_link.expires_at
        and destination_link.expires_at < datetime.now()
        and not destination_link.is_permanent
    ):
        language["warning"] = language["Instant-link-expired"]
        user = await check_user(request, db)
        return render(
            request,
            "home.html",
            {
                "request": request,
                "client_host": client_host,
                "user": user,
                "language": language,
            },
        )

    if not is_valid_url(destination_link.link):
        language["warning"] = language["Invalid-URL"]
        user = await check_user(request, db)
        return render(
            request,
            "home.html",
            {
                "request": request,
                "client_host": client_host,
                "user": user,
                "language": language,
            },
        )

    owner_id = destination_link.owner_id
    ip = get_client_ip(request)
    crud.create_user_ip(
        db=db,
        user_id=owner_id,
        ip=ip,
        origin=unique_link,
        description="Added by instant_access",
        ttl_hours=24,
    )
    language["success"] = (
        language["We-are-allowing-your-ip"]
        + ": "
        + str(ip)
        + ". "
        + language["You-will-be-redirected-to"]
        + destination_link.link
        + language["in-10-seconds"]
    )

    return render(
        request,
        "redirect.html",
        {
            "request": request,
            "link": destination_link.link,
            "language": language,
            "client_host": client_host,
        },
    )
