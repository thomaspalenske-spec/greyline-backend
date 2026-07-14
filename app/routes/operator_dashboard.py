from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()

templates = Jinja2Templates(directory="app/templates")


@router.get("/operator-dashboard", response_class=HTMLResponse)
async def operator_dashboard(request: Request):
    return templates.TemplateResponse("operator_dashboard.html", {"request": request})
