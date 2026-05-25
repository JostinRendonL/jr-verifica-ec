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

from datetime import datetime

from src.auth import (
    password_correcta, crear_cookie, cookie_valida, COOKIE_NAME, SESSION_MAX_AGE,
    ip_bloqueada, registrar_intento_fallido, limpiar_intentos, cedula_valida_ec,
)
from src.excel_io import leer_cedulas, generar_excel_plantilla
from src.processor import crear_job, obtener_job, ejecutar_job
from src.bg_client import consultar, extraer_bachiller, extraer_satje, extraer_setec
from src.processor import _calcular_semaforo
from src.historial_sqlite import (
    buscar_cache, registrar, listar as listar_historial, obtener_resultado,
    total_entradas, CACHE_TTL_SEG, calcular_stats,
    borrar_entrada, borrar_por_cedula, limpiar_todo,
)
from src.pdf_generator import generar_pdf
from src.verificaciones import obtener as obtener_verificacion
from src.obs import init_sentry, capture_exception
from src.compliance import (
    derecho_al_olvido as compliance_derecho_olvido,
    ejecutar_limpieza   as compliance_ejecutar_limpieza,
    estadisticas_compliance,
    RETENCION_MESES,
)
from src.scheduler import iniciar_scheduler, detener_scheduler
from src.metrics import setup_metrics

# Inicializar Sentry (opt-in con SENTRY_DSN). Debe ir ANTES de crear FastAPI.
init_sentry(servicio="verifica")

app = FastAPI(title="JR Verifica EC")

# Métricas Prometheus opt-in (si METRICS_ENABLED=1)
setup_metrics(app)


# ── Lifecycle: arrancar/parar el scheduler de tareas periódicas ──────────────

@app.on_event("startup")
async def _startup_scheduler():
    """Lanza tareas programadas (limpieza LOPDP semanal)."""
    iniciar_scheduler()


@app.on_event("shutdown")
async def _shutdown_scheduler():
    detener_scheduler()


# ── Middleware: headers de seguridad ─────────────────────────────────────────

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"]        = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # CSP permisiva para Tailwind + Google Fonts + Chart.js + Lucide icons
    # connect-src incluye unpkg/cdn para que sourcemaps de Lucide carguen sin warnings
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self' https://unpkg.com https://cdn.jsdelivr.net https://cdn.tailwindcss.com"
    )
    return response


def _ip_cliente(request: Request) -> str:
    """Obtiene la IP real del cliente (respeta Cloudflare/proxies)."""
    return (
        request.headers.get("cf-connecting-ip")
        or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )

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
async def health(deep: bool = False):
    """
    Healthcheck.
      /health         — liveness rápido (Docker HEALTHCHECK lo usa)
      /health?deep=1  — valida dependencias externas (bg-api, SQLite, scheduler)
    """
    import os as _os
    base = {
        "status":   "ok",
        "app":      "jr-verifica-ec",
        "version":  "2.0.0",
        "sentry":   "enabled" if _os.getenv("SENTRY_DSN") else "disabled",
    }
    if not deep:
        return base

    deps = {}

    # 1) SQLite — try a cheap query
    try:
        n = total_entradas()
        deps["sqlite"] = {"status": "ok", "total_entradas": n}
    except Exception as e:
        deps["sqlite"] = {"status": "down", "error": str(e)[:120]}

    # 2) bg-api
    try:
        import httpx as _httpx
        bg_url = _os.getenv("BG_API_URL", "http://dentaklin_bg-api:8000")
        async with _httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{bg_url}/health")
            deps["bg_api"] = {
                "status":    "ok" if r.status_code == 200 else "degraded",
                "http_code": r.status_code,
                "url":       bg_url,
            }
    except Exception as e:
        deps["bg_api"] = {"status": "down", "error": str(e)[:120]}

    # 3) Scheduler (compliance)
    try:
        stats = estadisticas_compliance()
        deps["scheduler"] = {
            "status":           "ok" if stats["scheduler"]["activo"] else "down",
            "proxima_limpieza": stats["scheduler"].get("proxima_limpieza"),
        }
    except Exception as e:
        deps["scheduler"] = {"status": "unknown", "error": str(e)[:120]}

    # Estado global
    overall = "ok"
    for v in deps.values():
        if v.get("status") == "down":
            overall = "down"
            break
        if v.get("status") == "degraded" and overall == "ok":
            overall = "degraded"

    return {**base, "status": overall, "deps": deps}


# ── Verificación pública de PDFs (NO requiere login) ─────────────────────────

@app.get("/verificar/{codigo}", response_class=HTMLResponse)
async def verificar_codigo(request: Request, codigo: str):
    """Endpoint PÚBLICO — cualquiera puede escanear el QR y validar autenticidad."""
    codigo = codigo.strip().upper()
    info = obtener_verificacion(codigo)

    return templates.TemplateResponse("verificar.html", {
        "request": request,
        "codigo":  codigo,
        "valido":  info is not None,
        "info":    info,
        "fecha":   datetime.fromtimestamp(info["timestamp"]).strftime("%d/%m/%Y %H:%M") if info else None,
    })


# ── Login ────────────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, error: str = "", bloqueado: int = 0):
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": error,
        "bloqueado_segundos": bloqueado,
    })


@app.post("/login")
async def login_submit(request: Request, password: str = Form(...)):
    ip = _ip_cliente(request)

    bloqueada, seg = ip_bloqueada(ip)
    if bloqueada:
        return RedirectResponse(url=f"/login?bloqueado={seg}", status_code=303)

    if not password_correcta(password):
        registrar_intento_fallido(ip)
        return RedirectResponse(url="/login?error=1", status_code=303)

    limpiar_intentos(ip)
    resp = RedirectResponse(url="/", status_code=303)
    resp.set_cookie(
        key=COOKIE_NAME,
        value=crear_cookie(),
        httponly=True,
        secure=True,            # solo HTTPS
        samesite="strict",      # protección CSRF
        max_age=SESSION_MAX_AGE,
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
    bachiller:   str = Form(""),
    satje:       str = Form(""),
    setec_check: str = Form(""),
    jr_session: str | None = Cookie(None),
):
    if not _autenticado(jr_session):
        return _redirect_login()

    # Determinar tipo según checkboxes
    quiere_b     = bool(bachiller)
    quiere_s     = bool(satje)
    quiere_setec = bool(setec_check)

    if not quiere_b and not quiere_s and not quiere_setec:
        return RedirectResponse(url="/?error=sin_seleccion", status_code=303)

    if quiere_b and quiere_s:
        tipo = "completo"
    elif quiere_b:
        tipo = "bachiller"
    elif quiere_s:
        tipo = "satje"
    else:
        tipo = "setec"   # sólo SETEC

    # Leer Excel
    contenido = await archivo.read()
    items, errores = leer_cedulas(contenido)

    if errores:
        return RedirectResponse(url=f"/?error=excel", status_code=303)
    if not items:
        return RedirectResponse(url="/?error=vacio", status_code=303)

    # Crear job y disparar background task
    job_id = crear_job(items, tipo, incluir_setec=quiere_setec)
    background_tasks.add_task(ejecutar_job, job_id, items, tipo, quiere_setec)

    return RedirectResponse(url=f"/job/{job_id}", status_code=303)


# ── Búsqueda individual ──────────────────────────────────────────────────────

@app.post("/buscar", response_class=HTMLResponse)
async def buscar_individual(
    request: Request,
    cedula:      str = Form(...),
    bachiller:   str = Form(""),
    satje:       str = Form(""),
    setec_check: str = Form(""),
    forzar:      str = Form(""),
    jr_session: str | None = Cookie(None),
):
    if not _autenticado(jr_session):
        return _redirect_login()

    cedula = (cedula or "").strip()
    if not cedula_valida_ec(cedula):
        return RedirectResponse(url="/?error=cedula_invalida", status_code=303)

    quiere_b     = bool(bachiller)
    quiere_s     = bool(satje)
    quiere_setec = bool(setec_check)
    if not quiere_b and not quiere_s and not quiere_setec:
        return RedirectResponse(url="/?error=sin_seleccion", status_code=303)

    if quiere_b and quiere_s:
        tipo = "completo"
    elif quiere_b:
        tipo = "bachiller"
    elif quiere_s:
        tipo = "satje"
    else:
        tipo = "setec"      # solo SETEC seleccionado

    # ── Cache ────────────────────────────────────────────────────────────────
    cached = None if forzar else buscar_cache(cedula, tipo)
    if cached:
        # Recalcular semáforo con lógica actual (no usar el guardado)
        if quiere_b and quiere_s:
            cached["semaforo"] = _calcular_semaforo(
                cached.get("bachiller") or {},
                cached.get("satje") or {},
                "completo",
            )
        # Recalcular nombre por si el caché es anterior a los fallbacks
        # (caché antiguo puede tener nombre="" aunque SATJE o SETEC tengan el dato)
        if not cached.get("nombre"):
            b_c  = cached.get("bachiller") or {}
            s_c  = cached.get("satje") or {}
            st_c = cached.get("setec") or {}
            if b_c.get("nombre"):
                cached["nombre"] = b_c["nombre"]
            elif s_c.get("nombre"):
                cached["nombre"] = s_c["nombre"]
            elif st_c.get("nombre"):
                cached["nombre"] = st_c["nombre"]
        resultado = {**cached, "_cache": True}
    else:
        # Si quiere SETEC y tipo no es ya "setec" → llamadas en paralelo
        if quiere_setec and tipo != "setec":
            raw, raw_setec = await asyncio.gather(
                consultar(cedula, tipo=tipo),
                consultar(cedula, tipo="setec"),
            )
        elif tipo == "setec":
            raw       = await consultar(cedula, tipo="setec")
            raw_setec = raw
        else:
            raw       = await consultar(cedula, tipo=tipo)
            raw_setec = raw

        b     = extraer_bachiller(raw)      if quiere_b     else None
        s     = extraer_satje(raw)          if quiere_s     else None
        setec = extraer_setec(raw_setec)    if quiere_setec else None

        sem = ""
        if quiere_b and quiere_s:
            sem = _calcular_semaforo(b or {}, s or {}, "completo")

        # Prioridad: Bachiller → SATJE → SETEC (la búsqueda individual no recibe
        # nombre desde el usuario, por eso la cadena empieza en bachiller).
        nombre = ""
        if b and b.get("nombre"):
            nombre = b.get("nombre")
        elif s and s.get("nombre"):
            nombre = s.get("nombre")
        elif setec and setec.get("nombre"):
            nombre = setec.get("nombre")

        resultado = {
            "cedula":    cedula,
            "nombre":    nombre,
            "bachiller": b,
            "satje":     s,
            "setec":     setec,
            "semaforo":  sem,
        }
        try:
            registrar(resultado, tipo)
        except Exception as e:
            capture_exception("buscar.registrar_historial", e,
                              extra={"cedula": cedula, "tipo": tipo})

    return templates.TemplateResponse("resultado.html", {
        "request":   request,
        "resultado": resultado,
        "fecha":     datetime.now().strftime("%d/%m/%Y %H:%M"),
        "desde_cache": bool(resultado.get("_cache")),
    })


# ── Compliance LOPDP ─────────────────────────────────────────────────────────
# Derecho al olvido (Art. 14) + Limpieza periódica (Art. 12).
# Multa máxima por incumplimiento: $1,800,000 USD.

@app.post("/derecho-al-olvido")
async def derecho_al_olvido_endpoint(
    cedula: str = Form(...),
    motivo: str = Form("Solicitud del titular"),
    jr_session: str | None = Cookie(None),
):
    """
    LOPDP Art. 14 — borra TODO rastro de una cédula (historial + verificaciones).
    Requiere autenticación admin (cookie de login en /verifica).

    En el futuro: agregar endpoint público con email-confirmación para que el
    titular pueda solicitarlo directamente sin pasar por RR.HH.
    """
    if not _autenticado(jr_session):
        return _redirect_login()

    cedula = (cedula or "").strip()
    if not cedula_valida_ec(cedula):
        return RedirectResponse(url="/historial?error=cedula_invalida", status_code=303)

    resultado = compliance_derecho_olvido(cedula, motivo=motivo)

    if resultado.get("ok"):
        n_hist = resultado.get("historial_borrado", 0)
        n_ver  = resultado.get("verificaciones_borradas", 0)
        return RedirectResponse(
            url=f"/historial?msg=olvido&cedula={cedula}&n_hist={n_hist}&n_ver={n_ver}",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/historial?error=olvido_fallo&detalle={resultado.get('error', 'desconocido')[:80]}",
        status_code=303,
    )


@app.post("/admin/limpiar-antiguos")
async def limpiar_antiguos_endpoint(
    meses: int = Form(None),
    jr_session: str | None = Cookie(None),
):
    """
    LOPDP Art. 12 — borra entradas con más de X meses (default RETENCION_MESES=12).
    Pensado para ser invocado por un Cron de Easypanel cada semana (Scheduled Task).

    Si se invoca sin meses: usa RETENCION_MESES de env (default 12).
    """
    if not _autenticado(jr_session):
        return _redirect_login()

    resultado = compliance_ejecutar_limpieza(meses=meses)
    # Responde JSON para que el Cron lo pueda parsear
    return resultado


@app.get("/admin/compliance")
async def compliance_status_endpoint(jr_session: str | None = Cookie(None)):
    """Resumen del estado de compliance — útil para dashboards o monitoring."""
    if not _autenticado(jr_session):
        return _redirect_login()
    return estadisticas_compliance()


# ── Dashboard ────────────────────────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse)
async def ver_dashboard(request: Request, jr_session: str | None = Cookie(None)):
    if not _autenticado(jr_session):
        return _redirect_login()

    stats = calcular_stats()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "stats":   stats,
    })


# ── Historial ────────────────────────────────────────────────────────────────

@app.get("/historial", response_class=HTMLResponse)
async def ver_historial(
    request: Request,
    cedula: str = "", semaforo: str = "",
    jr_session: str | None = Cookie(None),
):
    if not _autenticado(jr_session):
        return _redirect_login()

    entradas = listar_historial(filtro_cedula=cedula, filtro_semaforo=semaforo, limite=200)
    return templates.TemplateResponse("historial.html", {
        "request":   request,
        "entradas":  entradas,
        "total":     total_entradas(),
        "filtro_cedula":   cedula,
        "filtro_semaforo": semaforo,
        "ttl_horas": CACHE_TTL_SEG // 3600,
    })


@app.post("/pdf")
async def descargar_pdf_consulta(
    cedula:      str = Form(...),
    bachiller:   str = Form(""),
    satje:       str = Form(""),
    setec_check: str = Form(""),
    jr_session: str | None = Cookie(None),
):
    """Genera un PDF de una consulta — siempre usa cache si existe."""
    if not _autenticado(jr_session):
        return _redirect_login()

    cedula = (cedula or "").strip()
    if not cedula_valida_ec(cedula):
        return RedirectResponse(url="/?error=cedula_invalida", status_code=303)

    quiere_b     = bool(bachiller)
    quiere_s     = bool(satje)
    quiere_setec = bool(setec_check)

    if quiere_b and quiere_s:
        tipo = "completo"
    elif quiere_b:
        tipo = "bachiller"
    elif quiere_s:
        tipo = "satje"
    else:
        tipo = "setec"

    cached = buscar_cache(cedula, tipo)
    if not cached:
        return RedirectResponse(url="/?error=sin_datos_para_pdf", status_code=303)

    # Recalcular semáforo
    if quiere_b and quiere_s:
        cached["semaforo"] = _calcular_semaforo(
            cached.get("bachiller") or {},
            cached.get("satje") or {},
            "completo",
        )

    try:
        pdf_bytes = generar_pdf(cached)
    except Exception as e:
        capture_exception("pdf.descargar_consulta", e,
                          extra={"cedula": cedula, "tipo": tipo})
        return RedirectResponse(url=f"/?error=pdf_error&detalle={type(e).__name__}", status_code=303)

    nombre_seguro = (cached.get("nombre", "") or cedula).replace(" ", "_")[:40]
    filename = f"JR_Verifica_{cedula}_{nombre_seguro}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/historial/{entrada_id}/pdf")
async def pdf_desde_historial(
    entrada_id: str,
    jr_session: str | None = Cookie(None),
):
    if not _autenticado(jr_session):
        return _redirect_login()

    entrada = obtener_resultado(entrada_id)
    if not entrada:
        return RedirectResponse(url="/historial?error=no_encontrada", status_code=303)

    resultado = entrada["resultado"]
    # Recalcular semáforo con lógica actual
    if resultado.get("bachiller") and resultado.get("satje"):
        resultado["semaforo"] = _calcular_semaforo(
            resultado.get("bachiller") or {},
            resultado.get("satje") or {},
            "completo",
        )

    try:
        pdf_bytes = generar_pdf(resultado)
    except Exception as e:
        capture_exception("pdf.desde_historial", e,
                          extra={"entrada_id": entrada_id})
        return RedirectResponse(url=f"/historial/{entrada_id}?error=pdf_error&detalle={type(e).__name__}", status_code=303)

    cedula = resultado.get("cedula", "consulta")
    nombre_seguro = (resultado.get("nombre", "") or cedula).replace(" ", "_")[:40]
    filename = f"JR_Verifica_{cedula}_{nombre_seguro}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/historial/limpiar")
async def limpiar_historial(jr_session: str | None = Cookie(None)):
    """Borra TODO el historial/caché — útil cuando se necesita forzar re-consulta global."""
    if not _autenticado(jr_session):
        return _redirect_login()
    n = limpiar_todo()
    return RedirectResponse(url=f"/historial?msg=limpio&n={n}", status_code=303)


@app.post("/historial/{entrada_id}/borrar")
async def borrar_entrada_historial(entrada_id: str, jr_session: str | None = Cookie(None)):
    """Borra UNA entrada del historial."""
    if not _autenticado(jr_session):
        return _redirect_login()
    borrar_entrada(entrada_id)
    return RedirectResponse(url="/historial?msg=borrada", status_code=303)


@app.post("/historial/cedula/{cedula}/borrar")
async def borrar_cedula_historial(cedula: str, jr_session: str | None = Cookie(None)):
    """Borra TODAS las entradas de una cédula (re-fuerza próxima consulta)."""
    if not _autenticado(jr_session):
        return _redirect_login()
    n = borrar_por_cedula(cedula)
    return RedirectResponse(url=f"/historial?msg=borradas&n={n}", status_code=303)


@app.get("/historial/{entrada_id}", response_class=HTMLResponse)
async def ver_entrada_historial(
    request: Request, entrada_id: str,
    jr_session: str | None = Cookie(None),
):
    if not _autenticado(jr_session):
        return _redirect_login()

    entrada = obtener_resultado(entrada_id)
    if not entrada:
        return RedirectResponse(url="/historial?error=no_encontrada", status_code=303)

    return templates.TemplateResponse("resultado.html", {
        "request":   request,
        "resultado": entrada["resultado"],
        "fecha":     datetime.fromtimestamp(entrada["timestamp"]).strftime("%d/%m/%Y %H:%M"),
        "desde_cache": True,
        "edad_seg":  entrada["edad_seg"],
    })


# ── Búsqueda por lote ────────────────────────────────────────────────────────

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
