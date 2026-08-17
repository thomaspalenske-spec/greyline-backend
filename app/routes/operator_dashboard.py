import hashlib
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()

templates = Jinja2Templates(directory="app/templates")

_TEMPLATE = Path("app/templates/operator_dashboard.html")


def _code_version():
    """A stamp that changes whenever the dashboard's HTML/inline-JS changes (hash of the template
    file). An open tab embeds the value it loaded with and polls /dashboard-version; when the server
    returns a different stamp — i.e. we deployed new dashboard code — the tab reloads itself ONCE so
    new columns/panels appear without a manual hard-refresh. Best-effort; falls back to a constant."""
    try:
        return hashlib.sha256(_TEMPLATE.read_bytes()).hexdigest()[:12]
    except Exception:
        return "static"


@router.get("/operator-dashboard", response_class=HTMLResponse)
async def operator_dashboard(request: Request):
    # No-store so phones/browsers never render a stale copy of the page. Without this,
    # mobile Safari cached the HTML/JS and kept showing an old dashboard while the data
    # behind it was current.
    return templates.TemplateResponse(
        "operator_dashboard.html", {"request": request, "code_version": _code_version()},
        headers={"Cache-Control": "no-cache, no-store, must-revalidate",
                 "Pragma": "no-cache", "Expires": "0"},
    )


@router.get("/dashboard-version")
def dashboard_version():
    """Current dashboard code stamp — the open page polls this to self-reload after a deploy.
    Kept a plain (non-async) def so the endpoint-schema audit, which calls each GET bare, gets the
    dict directly rather than a coroutine."""
    return {"version": _code_version()}
