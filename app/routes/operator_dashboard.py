from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()

templates = Jinja2Templates(directory="app/templates")


@router.get("/operator-dashboard", response_class=HTMLResponse)
async def operator_dashboard(request: Request):
    # No-store so phones/browsers never render a stale copy of the page. Without this,
    # mobile Safari cached the HTML/JS and kept showing an old dashboard while the data
    # behind it was current.
    return templates.TemplateResponse(
        "operator_dashboard.html", {"request": request},
        headers={"Cache-Control": "no-cache, no-store, must-revalidate",
                 "Pragma": "no-cache", "Expires": "0"},
    )
