"""JR Verifica EC — App de búsqueda batch de Bachiller + SATJE."""
import os
import asyncio
from pathlib import Path

from fastapi import FastAPI, Request, Form, UploadFile, File, Cookie, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from dotenv import load_dotenv
load_dotenv()

from src.auth import password_correcta, crear_cookie, cookie_valida, COOKIE_NAME
from src.excel_io import leer_cedulas, generar_excel_plantilla
from src.processor import crear_job, obtener_job, ejecutar_job

app = FastAPI(title="JR Verifica EC")

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Crear carpeta static si no existe (no es crítica, todo va por CDN)
_static_dir = BASE_DIR / "static"
_static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# ── Helper de autenticación ──────────────────────────────────────────────────

def _autenticado(jr_session: str | None) -> bool:
    return cookie_valida(jr_session)


def _redirect_login() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=303)


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "app": "jr-verifica-ec", "version": "1.0.0"}


# ── Login ────────────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, error: str = ""):
    return templates.TemplateResponse("login.html", {"request": request, "error": error})


@app.post("/login")
async def login_submit(password: str = Form(...)):
    if not password_correcta(password):
        return RedirectResponse(url="/login?error=1", status_code=303)
    resp = RedirectResponse(url="/", status_code=303)
    resp.set_cookie(
        key=COOKIE_NAME,
        value=crear_cookie(),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,  # 7 días
    )
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# ── Home / Upload ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, jr_session: str | None = Cookie(None)):
    if not _autenticado(jr_session):
        return _redirect_login()
    return templates.TemplateResponse("upload.html", {"request": request})


@app.get("/plantilla")
async def descargar_plantilla(jr_session: str | None = Cookie(None)):
    if not _autenticado(jr_session):
        return _redirect_login()
    excel_bytes = generar_excel_plantilla()
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="plantilla_cedulas.xlsx"'},
    )


# ── Procesamiento ────────────────────────────────────────────────────────────

@app.post("/procesar")
async def procesar(
    background_tasks: BackgroundTasks,
    archivo: UploadFile = File(...),
    bachiller: str = Form(""),
    satje:     str = Form(""),
    jr_session: str | None = Cookie(None),
):
    if not _autenticado(jr_session):
        return _redirect_login()

    # Determinar tipo según checkboxes
    quiere_b = bool(bachiller)
    quiere_s = bool(satje)

    if not quiere_b and not quiere_s:
        return RedirectResponse(url="/?error=sin_seleccion", status_code=303)

    if quiere_b and quiere_s:
        tipo = "completo"
    elif quiere_b:
        tipo = "bachiller"
    else:
        tipo = "satje"

    # Leer Excel
    contenido = await archivo.read()
    items, errores = leer_cedulas(contenido)

    if errores:
        return RedirectResponse(url=f"/?error=excel", status_code=303)
    if not items:
        return RedirectResponse(url="/?error=vacio", status_code=303)

    # Crear job y disparar background task
    job_id = crear_job(items, tipo)
    background_tasks.add_task(ejecutar_job, job_id, items, tipo)

    return RedirectResponse(url=f"/job/{job_id}", status_code=303)


@app.get("/job/{job_id}", response_class=HTMLResponse)
async def ver_job(request: Request, job_id: str, jr_session: str | None = Cookie(None)):
    if not _autenticado(jr_session):
        return _redirect_login()

    job = obtener_job(job_id)
    if not job:
        return RedirectResponse(url="/?error=job_no_encontrado", status_code=303)

    return templates.TemplateResponse("job.html", {"request": request, "job": job})


@app.get("/job/{job_id}/status")
async def status_job(job_id: str, jr_session: str | None = Cookie(None)):
    """Endpoint JSON para polling desde el frontend."""
    if not _autenticado(jr_session):
        return {"error": "no_auth"}

    job = obtener_job(job_id)
    if not job:
        return {"error": "not_found"}

    return {
        "id":         job["id"],
        "tipo":       job["tipo"],
        "estado":     job["estado"],
        "total":      job["total"],
        "procesados": job["procesados"],
        "progreso":   round(100 * job["procesados"] / max(1, job["total"]), 1),
        "error":      job.get("error", ""),
        "puede_descargar": job["estado"] == "completado" and job.get("excel_bytes") is not None,
    }


@app.get("/job/{job_id}/descargar")
async def descargar_resultado(job_id: str, jr_session: str | None = Cookie(None)):
    if not _autenticado(jr_session):
        return _redirect_login()

    job = obtener_job(job_id)
    if not job or not job.get("excel_bytes"):
        return RedirectResponse(url="/?error=no_disponible", status_code=303)

    nombre = f"resultados_{job['tipo']}_{job_id}.xlsx"
    return Response(
        content=job["excel_bytes"],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


# ── Startup ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    print("🚀 JR Verifica EC — listo")
    print(f"   BG_API_URL: {os.getenv('BG_API_URL', '(no configurado)')}")
    print(f"   MAX_WORKERS: {os.getenv('MAX_WORKERS', '3')}")
