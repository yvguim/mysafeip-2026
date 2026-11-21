import ipaddress

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import crud
import models
from auth import check_user_language, get_current_user
from database import get_db
from security import get_client_ip
from ttl import MAX_TTL_HOURS, validate_ttl_hours

router = APIRouter(prefix="/ips", tags=["ips"], dependencies=[Depends(get_db)])
router.mount("/static", StaticFiles(directory="templates/static"), name="static")
templates = Jinja2Templates(directory="templates")


def render(request: Request, template: str, context: dict):
    return templates.TemplateResponse(
        request, template, context | {"max_ttl_hours": MAX_TTL_HOURS}
    )


def validate_ip(ip: str) -> bool:
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


@router.get("/config/")
async def list_ips(
    request: Request,
    db=Depends(get_db),
    language=Depends(check_user_language),
    current_user: models.User = Depends(get_current_user),
):
    ips = crud.get_ips(db, user=current_user)
    if request.headers.get("Cli"):
        return [
            {"owner": ip.owner.email, "value": ip.value, "description": ip.description}
            for ip in ips
        ]
    return render(
        request,
        "ips.html",
        {
            "request": request,
            "user": current_user,
            "ips": ips,
            "ip": get_client_ip(request),
            "language": language,
            "default_ttl": current_user.ip_default_ttl_hours,
        },
    )


@router.post("/config/")
async def post_ips(
    request: Request,
    ip=Form(""),
    ip_id=Form(""),
    description=Form(""),
    action=Form(""),
    ttl_hours=Form(""),
    is_permanent=Form(""),
    custom_ttl_hours=Form(""),
    db=Depends(get_db),
    language=Depends(check_user_language),
    current_user: models.User = Depends(get_current_user),
):
    ctx = {"request": request, "user": current_user, "language": language}

    if action == "delete":
        if not crud.delete_ip(db, ip_id, owner_id=current_user.id):
            raise HTTPException(status_code=404, detail="Resource not found")
        language["success"] = language["ip-deleted-successfully"]
        ip = get_client_ip(request)

    if action == "create":
        if not ip:
            ip = get_client_ip(request)
        if not validate_ip(ip):
            language["warning"] = language["Invalid-IP-address"]
            return render(
                request,
                "ips.html",
                ctx | {"ips": crud.get_ips(db, user=current_user), "ip": ip},
            )

        permanent = is_permanent == "true"
        try:
            selected_ttl = (
                custom_ttl_hours
                if ttl_hours == "custom"
                else ttl_hours or current_user.ip_default_ttl_hours
            )
            ttl = None if permanent else validate_ttl_hours(selected_ttl)
        except ValueError:
            language["warning"] = language["Invalid-duration"]
            return render(
                request,
                "ips.html",
                ctx
                | {
                    "ips": crud.get_ips(db, user=current_user),
                    "ip": ip,
                    "default_ttl": current_user.ip_default_ttl_hours,
                },
            )

        ip_created = crud.create_user_ip(
            db=db,
            user_id=current_user.id,
            ip=ip,
            origin=language["Created-Manually"],
            description=description,
            ttl_hours=ttl,
            is_permanent=permanent,
        )
        if ip_created:
            language["success"] = str(ip_created.value) + language["is-now-trusted"]

    return render(
        request,
        "ips.html",
        ctx
        | {
            "ips": crud.get_ips(db, user=current_user),
            "ip": ip,
            "default_ttl": current_user.ip_default_ttl_hours,
        },
    )
