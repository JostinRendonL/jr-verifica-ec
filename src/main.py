"""JR Verifica EC — App de búsqueda batch de Bachiller + SATJE."""
import os
import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, Request, Form, UploadFile, File, Cookie, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

# Logging estructurado — reemplaza print() para que Loki/Sentry/journalctl
# puedan filtrar por nivel y módulo.
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("verifica")


def _to_bool(v) -> bool:
    """Form values son siempre str. '1','true','on','yes' → True; resto → False.
    Reemplaza bool(str) que era frágil (bool('0') == True)."""
    if isinstance(v, bool):
        return v
    s = str(v or "").strip().lower()
    return s in ("1", "true", "on", "yes", "si", "sí")

from dotenv import load_dotenv
load_dotenv()

from datetime import datetime

# Timezone Ecuador (UTC-5) — para que emails y respuestas muestren hora local
try:
    from zoneinfo import ZoneInfo
    _TZ_EC = ZoneInfo("America/Guayaquil")
except ImportError:
    from datetime import timezone, timedelta
    _TZ_EC = timezone(timedelta(hours=-5))

from src.auth import (
    crear_cookie, decodificar_cookie, COOKIE_NAME, SESSION_MAX_AGE,
    ip_bloqueada, registrar_intento_fallido, limpiar_intentos, cedula_valida_ec,
)
from src import usuarios, password_reset, audit_log
from src.mailer import enviar_email


def _notificar_password_cambiada(usuario: "usuarios.Usuario", metodo: str,
                                  ip: str) -> None:
    """
    Envía un email de seguridad al usuario notificándole que su pass
    fue cambiada. Best-effort: nunca lanza excepciones.

    `metodo` es una descripción legible: 'Cambio desde el perfil',
    'Reset por email', 'Reset por admin', etc.
    """
    try:
        html = templates.get_template("email_password_cambiada.html").render(
            nombre=usuario.nombre,
            fecha=datetime.now(_TZ_EC).strftime("%d/%m/%Y %H:%M"),
            metodo=metodo,
            ip=ip or "desconocida",
        )
        texto = (
            f"Hola {usuario.nombre},\n\n"
            f"Te confirmamos que tu contraseña en JR Verifica EC fue cambiada.\n\n"
            f"Cuándo: {datetime.now(_TZ_EC).strftime('%d/%m/%Y %H:%M')}\n"
            f"Método: {metodo}\n"
            f"IP:     {ip or 'desconocida'}\n\n"
            f"Si no fuiste vos, cambiá tu contraseña inmediatamente y contactá al administrador."
        )
        enviar_email(
            to=usuario.email,
            subject="🔐 Tu contraseña fue cambiada — JR Verifica EC",
            html=html,
            text=texto,
        )
    except Exception as e:
        capture_exception("notificar_password_cambiada", e,
                          extra={"usuario_id": usuario.id})
from src.excel_io import leer_cedulas, generar_excel_plantilla
from src.processor import crear_job, obtener_job, ejecutar_job
from src.bg_client import consultar, extraer_bachiller, extraer_satje, extraer_setec, extraer_fiscalia
from src.processor import _calcular_semaforo
from src.historial_sqlite import (
    buscar_cache, registrar, listar as listar_historial, obtener_resultado,
    total_entradas, CACHE_TTL_SEG, calcular_stats,
    borrar_entrada, borrar_por_cedula, borrar_multiples, limpiar_todo,
    actualizar_nombre, actualizar_semaforo,
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

# ── Rate limiting (slowapi) — protege endpoints caros del scraping ──────────
# Disable con RATE_LIMIT_ENABLED=0. Keys por usuario logueado (uid),
# fallback a IP cuando no hay sesión (login).
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address


def _rate_key(request: Request) -> str:
    """Identidad para rate limiting: uid si está logueado, IP si no."""
    cookie = request.cookies.get(COOKIE_NAME)
    payload = decodificar_cookie(cookie) if cookie else None
    if payload and payload.get("uid"):
        return f"uid:{payload['uid']}"
    return f"ip:{get_remote_address(request)}"


_RL_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "1") != "0"
limiter = Limiter(key_func=_rate_key, enabled=_RL_ENABLED, default_limits=[])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Lifecycle: arrancar/parar el scheduler de tareas periódicas ──────────────

@app.on_event("startup")
async def _startup_scheduler():
    """Lanza tareas programadas (limpieza LOPDP semanal)."""
    iniciar_scheduler()


@app.on_event("startup")
async def _startup_bootstrap_admin():
    """Migra la DB multi-usuario y crea el admin inicial si no existe."""
    try:
        u = usuarios.bootstrap_admin_si_falta()
        if u:
            logger.info("admin bootstrap creado: %s", u.email)
    except Exception as e:
        logger.warning("bootstrap admin fallo: %s", e)
        capture_exception("startup.bootstrap_admin", e)


@app.on_event("startup")
async def _startup_reset_admin_si_pedido():
    """Fallback: si ADMIN_RESET env var existe, resetea la pass del admin."""
    try:
        u = usuarios.bootstrap_reset_admin_si_pedido()
        if u:
            logger.info("admin reseteado vía ADMIN_RESET: %s", u.email)
    except Exception as e:
        logger.warning("reset admin fallo: %s", e)
        capture_exception("startup.reset_admin", e)


@app.on_event("shutdown")
async def _shutdown_scheduler():
    detener_scheduler()


# ── Middleware: headers de seguridad ─────────────────────────────────────────

@app.middleware("http")
async def contexto_usuario(request: Request, call_next):
    """
    Pone request.state.usuario (Usuario | None) para que templates lo usen
    en el navbar. Y si el usuario tiene debe_cambiar_pass=1, redirige a
    /perfil (excepto en rutas exentas para evitar loop).
    """
    cookie = request.cookies.get(COOKIE_NAME)
    u = _usuario_actual(cookie)
    request.state.usuario = u

    path = request.url.path
    rutas_exentas = (
        path.startswith("/perfil") or path.startswith("/logout")
        or path.startswith("/static") or path.startswith("/login")
        or path == "/health" or path.startswith("/verificar/")
    )
    if u and u.debe_cambiar_pass and not rutas_exentas:
        return RedirectResponse(url="/perfil?debe_cambiar=1", status_code=303)
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"]        = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # CSP minimal — v2 solo usa Google Fonts externamente. Scripts inline siguen
    # permitidos (unsafe-inline) por handlers onclick en templates; pendiente
    # migrar a addEventListener para endurecer.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'"
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

# ── Frontend React (build de Vite) ─────────────────────────────────────────
# El build de Vite va a src/static/frontend/ (ver vite.config.ts → build.outDir).
# En producción FastAPI sirve el SPA directamente.
# En desarrollo local, Vite dev server corre en :5173 con proxy → :8000.
_frontend_dir = _static_dir / "frontend"
if _frontend_dir.exists():
    # Assets JS/CSS del build
    _assets_dir = _frontend_dir / "assets"
    if _assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="frontend-assets")
    logger.info("React build encontrado en %s", _frontend_dir)
else:
    logger.info("Sin build React en %s — solo Jinja2 disponible", _frontend_dir)

# Fallback SPA — siempre registrado, independiente de si el build existe
from fastapi.responses import FileResponse as _FileResponse

@app.get("/app", include_in_schema=False)
@app.get("/app/{full_path:path}", include_in_schema=False)
async def _spa_fallback(full_path: str = ""):
    """Sirve el SPA de React. Funciona con React Router (client-side routing)."""
    index = _frontend_dir / "index.html"
    if not index.exists():
        from fastapi.responses import JSONResponse as _JSONResponse
        return _JSONResponse(
            {"error": "Frontend no compilado", "hint": "Ejecuta npm run build en /frontend"},
            status_code=503,
        )
    return _FileResponse(str(index))


# Redirects cortos: /busqueda → /app/busqueda, etc.
# Así el usuario puede usar la URL corta y también funciona el basename="/app" de React.
@app.get("/busqueda", include_in_schema=False)
async def _redir_busqueda(): return RedirectResponse("/app/busqueda", status_code=302)

@app.get("/panel", include_in_schema=False)
async def _redir_panel(): return RedirectResponse("/app/panel", status_code=302)

@app.get("/lote", include_in_schema=False)
async def _redir_lote(): return RedirectResponse("/app/lote", status_code=302)

@app.get("/usuarios", include_in_schema=False)
async def _redir_usuarios(): return RedirectResponse("/app/usuarios", status_code=302)


# ── Helpers de autenticación multi-usuario ──────────────────────────────────

async def _noop_async():
    """Coroutine vacia para usar en asyncio.gather cuando un modulo no se solicita."""
    return None


def _usuario_actual(jr_session: str | None) -> usuarios.Usuario | None:
    """Devuelve el Usuario logueado o None. Valida cookie + que siga activo."""
    payload = decodificar_cookie(jr_session)
    if not payload:
        return None
    u = usuarios.obtener_por_id(payload.get("uid", ""))
    if not u or not u.activo:
        return None
    return u


def _autenticado(jr_session: str | None) -> bool:
    """[LEGACY] Sigue funcionando: True si hay usuario válido en la cookie."""
    return _usuario_actual(jr_session) is not None


def _es_admin(jr_session: str | None) -> bool:
    u = _usuario_actual(jr_session)
    return u is not None and u.rol == "admin"


def _redirect_login() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=303)


def _redirect_perfil_si_debe_cambiar(u: usuarios.Usuario, path_actual: str) -> RedirectResponse | None:
    """
    Si el usuario tiene debe_cambiar_pass=1, redirigir a /perfil
    salvo que ya esté en /perfil o /logout (para no crear loop).
    """
    if not u.debe_cambiar_pass:
        return None
    if path_actual.startswith("/perfil") or path_actual.startswith("/logout") or path_actual.startswith("/static"):
        return None
    return RedirectResponse(url="/perfil?debe_cambiar=1", status_code=303)


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


# ── Auth API (para React frontend) ──────────────────────────────────────────

@app.get("/me")
async def me(jr_session: str | None = Cookie(None)):
    """Devuelve el usuario autenticado actual. Usado por el frontend React."""
    from fastapi.responses import JSONResponse
    u = _usuario_actual(jr_session)
    if not u:
        return JSONResponse({"autenticado": False})
    return JSONResponse({
        "autenticado": True,
        "usuario_id":  u.id,
        "email":       u.email,
        "rol":         u.rol,
        "nombre":      u.nombre,
    })


# ── JSON API (para React frontend) ──────────────────────────────────────────
# Todos estos endpoints devuelven JSON y coexisten con los endpoints HTML
# existentes. El frontend React los consume; las plantillas Jinja2 siguen
# funcionando mientras dure la migración.

@app.post("/api/buscar")
@limiter.limit("30/minute")
async def api_buscar(
    request: Request,
    cedula:         str = Form(...),
    bachiller:      str = Form(""),
    satje:          str = Form(""),
    setec_check:    str = Form(""),
    fiscalia_check: str = Form(""),
    forzar:         str = Form(""),
    jr_session: str | None = Cookie(None),
):
    """Búsqueda individual — devuelve JSON con el resultado completo."""
    from fastapi.responses import JSONResponse
    u = _usuario_actual(jr_session)
    if not u:
        return JSONResponse({"error": "no_auth"}, status_code=401)

    cedula = (cedula or "").strip()
    if not cedula_valida_ec(cedula):
        return JSONResponse({"error": "cedula_invalida"}, status_code=400)

    quiere_b        = bool(bachiller)
    quiere_s        = bool(satje)
    quiere_setec    = bool(setec_check)
    quiere_fiscalia = bool(fiscalia_check)
    if not quiere_b and not quiere_s and not quiere_setec and not quiere_fiscalia:
        return JSONResponse({"error": "sin_seleccion"}, status_code=400)

    if quiere_b and quiere_s:
        tipo = "completo"
    elif quiere_b:
        tipo = "bachiller"
    elif quiere_s:
        tipo = "satje"
    else:
        tipo = "setec"

    cached = None if forzar else buscar_cache(cedula, tipo)
    if cached:
        if quiere_fiscalia and cached.get("fiscalia") is None:
            raw_fisc = await consultar(cedula, tipo="fiscalia")
            cached["fiscalia"] = extraer_fiscalia(raw_fisc)
            try:
                registrar(cached, tipo, usuario_id=u.id)
            except Exception as _e:
                logger.warning("registrar() fallo (re-fetch fiscalia) ced=%s: %s", cedula, _e)
                capture_exception("buscar.registrar_refetch_fiscalia", _e, extra={"cedula": cedula})
        if quiere_b and quiere_s:
            cached["semaforo"] = _calcular_semaforo(
                cached.get("bachiller") or {},
                cached.get("satje") or {},
                "completo",
                fiscalia=cached.get("fiscalia"),
            )
        resultado = {**cached, "_cache": True}
    else:
        _fr = _to_bool(forzar)  # propagar al bg-api
        coros = [consultar(cedula, tipo=tipo, force_refresh=_fr)]
        coros.append(consultar(cedula, tipo="setec", force_refresh=_fr) if quiere_setec and tipo != "setec" else _noop_async())
        coros.append(consultar(cedula, tipo="fiscalia", force_refresh=_fr) if quiere_fiscalia else _noop_async())
        raw_results = await asyncio.gather(*coros)
        raw          = raw_results[0]
        raw_setec    = raw_results[1] if (quiere_setec and tipo != "setec") else (raw if tipo == "setec" else None)
        raw_fiscalia = raw_results[2] if quiere_fiscalia else None
        b        = extraer_bachiller(raw)         if quiere_b    else None
        s        = extraer_satje(raw)             if quiere_s    else None
        setec    = extraer_setec(raw_setec)       if raw_setec   else None
        fiscalia = extraer_fiscalia(raw_fiscalia) if raw_fiscalia else None
        sem = ""
        if quiere_b and quiere_s:
            sem = _calcular_semaforo(b or {}, s or {}, "completo", fiscalia=fiscalia)
        nombre = ""
        for src in (b, s, setec):
            if src and src.get("nombre"):
                nombre = src["nombre"]
                break
        resultado = {
            "cedula": cedula, "nombre": nombre,
            "bachiller": b, "satje": s, "setec": setec, "fiscalia": fiscalia,
            "semaforo": sem, "_cache": False,
        }
        try:
            registrar(resultado, tipo, usuario_id=u.id)
        except Exception as e:
            capture_exception("api.buscar.registrar", e, extra={"cedula": cedula})

    resultado["fecha"] = datetime.now(_TZ_EC).strftime("%d/%m/%Y %H:%M")
    return JSONResponse(resultado)


@app.get("/api/historial")
async def api_listar_historial(
    cedula: str = "",
    semaforo: str = "",
    limite: int = 200,
    jr_session: str | None = Cookie(None),
):
    """Lista el historial de verificaciones en JSON."""
    from fastapi.responses import JSONResponse
    u = _usuario_actual(jr_session)
    if not u:
        return JSONResponse({"error": "no_auth"}, status_code=401)
    entradas = listar_historial(
        filtro_cedula=cedula,
        filtro_semaforo=semaforo,
        limite=min(limite, 500),
    )
    return JSONResponse({
        "entradas": entradas,
        "total":    total_entradas(),
    })


@app.get("/api/historial/cedula/{cedula}")
async def api_resultado_por_cedula(cedula: str, jr_session: str | None = Cookie(None)):
    """Devuelve el resultado más reciente de una cédula desde el historial."""
    from fastapi.responses import JSONResponse
    u = _usuario_actual(jr_session)
    if not u:
        return JSONResponse({"error": "no_auth"}, status_code=401)
    cached = buscar_cache(cedula, "completo") or buscar_cache(cedula, "bachiller") or \
             buscar_cache(cedula, "satje") or buscar_cache(cedula, "setec")
    if not cached:
        return JSONResponse({"error": "no_encontrado"}, status_code=404)
    return JSONResponse(cached)


@app.get("/api/historial/{entrada_id}")
async def api_entrada_historial(entrada_id: str, jr_session: str | None = Cookie(None)):
    """Devuelve el resultado completo de una entrada por ID."""
    from fastapi.responses import JSONResponse
    u = _usuario_actual(jr_session)
    if not u:
        return JSONResponse({"error": "no_auth"}, status_code=401)
    entrada = obtener_resultado(entrada_id)
    if not entrada:
        return JSONResponse({"error": "no_encontrada"}, status_code=404)
    return JSONResponse(entrada)


@app.post("/api/procesar")
@limiter.limit("5/minute")
async def api_procesar(
    request: Request,
    background_tasks: BackgroundTasks,
    archivo: UploadFile = File(...),
    bachiller:      str = Form(""),
    satje:          str = Form(""),
    setec_check:    str = Form(""),
    fiscalia_check: str = Form(""),
    forzar:         str = Form(""),
    jr_session: str | None = Cookie(None),
):
    """Inicia un job de procesamiento por lote y devuelve el job_id en JSON."""
    from fastapi.responses import JSONResponse
    u = _usuario_actual(jr_session)
    if not u:
        return JSONResponse({"error": "no_auth"}, status_code=401)

    quiere_b        = bool(bachiller)
    quiere_s        = bool(satje)
    quiere_setec    = bool(setec_check)
    quiere_fiscalia = bool(fiscalia_check)
    if not quiere_b and not quiere_s and not quiere_setec and not quiere_fiscalia:
        return JSONResponse({"error": "sin_seleccion"}, status_code=400)

    if quiere_b and quiere_s:
        tipo = "completo"
    elif quiere_b:
        tipo = "bachiller"
    elif quiere_s:
        tipo = "satje"
    else:
        tipo = "setec"

    contenido = await archivo.read()
    items, errores = leer_cedulas(contenido)
    if errores:
        return JSONResponse({"error": "excel_invalido", "detalle": errores[:5]}, status_code=400)
    if not items:
        return JSONResponse({"error": "archivo_vacio"}, status_code=400)

    job_id = crear_job(items, tipo, incluir_setec=quiere_setec,
                       incluir_fiscalia=quiere_fiscalia, usuario_id=u.id)
    background_tasks.add_task(ejecutar_job, job_id, items, tipo,
                               quiere_setec, quiere_fiscalia, u.id,
                               _to_bool(forzar))
    return JSONResponse({"job_id": job_id, "total": len(items)})


@app.get("/api/stats")
async def api_stats(jr_session: str | None = Cookie(None)):
    """Estadísticas del dashboard en JSON."""
    from fastapi.responses import JSONResponse
    u = _usuario_actual(jr_session)
    if not u:
        return JSONResponse({"error": "no_auth"}, status_code=401)
    return JSONResponse(calcular_stats())


@app.get("/api/usuarios")
async def api_listar_usuarios(jr_session: str | None = Cookie(None)):
    """Lista de usuarios — solo admin."""
    from fastapi.responses import JSONResponse
    u = _usuario_actual(jr_session)
    if not u or u.rol != "admin":
        return JSONResponse({"error": "no_auth"}, status_code=403)
    lista = usuarios.listar(solo_activos=False)
    return JSONResponse([
        {
            "id":         uu.id,
            "email":      uu.email,
            "nombre":     uu.nombre,
            "rol":        uu.rol,
            "activo":     uu.activo,
            "creado_ts":  uu.creado_ts,
            "ultimo_login": uu.ultimo_login,
        }
        for uu in lista
    ])


@app.post("/api/usuarios/{user_id}/desactivar")
async def api_desactivar_usuario(user_id: str, jr_session: str | None = Cookie(None)):
    from fastapi.responses import JSONResponse
    u = _usuario_actual(jr_session)
    if not u or u.rol != "admin":
        return JSONResponse({"error": "no_auth"}, status_code=403)
    try:
        usuarios.desactivar(user_id, ejecutor_id=u.id)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/usuarios/{user_id}/reactivar")
async def api_reactivar_usuario(user_id: str, jr_session: str | None = Cookie(None)):
    from fastapi.responses import JSONResponse
    u = _usuario_actual(jr_session)
    if not u or u.rol != "admin":
        return JSONResponse({"error": "no_auth"}, status_code=403)
    usuarios.reactivar(user_id)
    return JSONResponse({"ok": True})


@app.post("/api/usuarios/crear")
async def api_crear_usuario(
    email:  str = Form(...),
    nombre: str = Form(...),
    rol:    str = Form("operador"),
    jr_session: str | None = Cookie(None),
):
    from fastapi.responses import JSONResponse
    import secrets, string
    u = _usuario_actual(jr_session)
    if not u or u.rol != "admin":
        return JSONResponse({"error": "no_auth"}, status_code=403)
    try:
        # Generar contraseña temporal segura
        alphabet = string.ascii_letters + string.digits
        temp_pass = "".join(secrets.choice(alphabet) for _ in range(12))
        nuevo = usuarios.crear_usuario(
            email=email, nombre=nombre, password=temp_pass,
            rol=rol, creado_por=u.id, debe_cambiar_pass=True,
        )
        return JSONResponse({"ok": True, "id": nuevo.id, "temp_password": temp_pass})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ── API: Historial acciones (para React) ─────────────────────────────────────

@app.post("/api/historial/limpiar")
async def api_limpiar_historial(jr_session: str | None = Cookie(None)):
    """Borra TODO el historial/caché — devuelve JSON."""
    from fastapi.responses import JSONResponse
    u = _usuario_actual(jr_session)
    if not u:
        return JSONResponse({"error": "no_auth"}, status_code=401)
    n = limpiar_todo()
    return JSONResponse({"ok": True, "n": n})


@app.post("/api/derecho-al-olvido")
async def api_derecho_al_olvido(
    cedula: str = Form(...),
    motivo: str = Form("Solicitud del titular"),
    jr_session: str | None = Cookie(None),
):
    """Derecho al olvido LOPDP Art. 14 — borra todo rastro de una cédula. Devuelve JSON."""
    from fastapi.responses import JSONResponse
    u = _usuario_actual(jr_session)
    if not u:
        return JSONResponse({"error": "no_auth"}, status_code=401)
    if not cedula_valida_ec(cedula):
        return JSONResponse({"error": "cedula_invalida"}, status_code=400)
    try:
        resultado = compliance_derecho_olvido(cedula, motivo=motivo)
        if resultado.get("ok"):
            return JSONResponse({
                "ok": True,
                "n_hist": resultado.get("historial_borrado", 0),
                "n_ver":  resultado.get("verificaciones_borradas", 0),
            })
        return JSONResponse({"error": resultado.get("error", "fallo_desconocido")}, status_code=500)
    except Exception as e:
        capture_exception("api.derecho_al_olvido", e, extra={"cedula": cedula})
        return JSONResponse({"error": str(e)[:120]}, status_code=500)


# ── Login ────────────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, error: str = "", bloqueado: int = 0,
                     reseteada: int = 0):
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": error,
        "bloqueado_segundos": bloqueado,
        "reseteada": bool(reseteada),
    })


@app.post("/login")
@limiter.limit("10/minute")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    ip = _ip_cliente(request)

    bloqueada, seg = ip_bloqueada(ip)
    if bloqueada:
        return RedirectResponse(url=f"/login?bloqueado={seg}", status_code=303)

    u = usuarios.autenticar(email, password)
    if not u:
        registrar_intento_fallido(ip)
        return RedirectResponse(url="/login?error=1", status_code=303)

    limpiar_intentos(ip)

    # Si el admin lo creó con flag debe_cambiar_pass=1, lo mandamos a /perfil
    destino = "/perfil?debe_cambiar=1" if u.debe_cambiar_pass else "/"
    resp = RedirectResponse(url=destino, status_code=303)
    resp.set_cookie(
        key=COOKIE_NAME,
        value=crear_cookie(uid=u.id, rol=u.rol),
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=SESSION_MAX_AGE,
    )
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# ── Olvido de contraseña ─────────────────────────────────────────────────────

def _base_url(request: Request) -> str:
    """URL base de la app (https://verifica.dentaklin.shop). Respeta APP_BASE_URL si está definida."""
    base = os.getenv("APP_BASE_URL", "").rstrip("/")
    if base:
        return base
    # Fallback: reconstruir desde el request
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    host   = request.headers.get("host") or "localhost"
    return f"{scheme}://{host}"


@app.get("/olvide-pass", response_class=HTMLResponse)
async def olvide_pass_form(request: Request, ok: int = 0):
    return templates.TemplateResponse("olvide_pass.html", {
        "request": request,
        "ok":      bool(ok),
    })


@app.post("/olvide-pass")
async def olvide_pass_submit(request: Request, email: str = Form(...)):
    """
    Genera token + envía email. Responde igual exista o no el email
    (anti-enumeración: no revelar qué emails están registrados).
    """
    ip = _ip_cliente(request)
    bloqueada, _ = ip_bloqueada(ip)
    if bloqueada:
        return RedirectResponse(url="/olvide-pass?ok=1", status_code=303)

    u = usuarios.obtener_por_email(email)
    if u and u.activo:
        try:
            token = password_reset.generar_token(u.id, ip_origen=ip)
            link = f"{_base_url(request)}/reset-pass/{token}"
            html = templates.get_template("email_reset.html").render(
                nombre=u.nombre, link=link, ttl_min=60,
            )
            texto = (
                f"Hola {u.nombre},\n\n"
                f"Recibimos una solicitud para resetear tu contraseña en JR Verifica EC.\n"
                f"Si fuiste tú, abre este enlace (válido 1 hora):\n\n"
                f"{link}\n\n"
                f"Si no fuiste tú, ignora este email."
            )
            enviar_email(
                to=u.email,
                subject="Recupera tu contraseña — JR Verifica EC",
                html=html,
                text=texto,
            )
        except Exception as e:
            capture_exception("olvide_pass.enviar", e, extra={"email": email})
    else:
        # Pequeño rate-limit anti-flood aunque sea por IP
        registrar_intento_fallido(ip)

    return RedirectResponse(url="/olvide-pass?ok=1", status_code=303)


@app.get("/reset-pass/{token}", response_class=HTMLResponse)
async def reset_pass_form(request: Request, token: str, error: str = ""):
    info = password_reset.validar_token(token)
    if not info:
        return templates.TemplateResponse("reset_pass.html", {
            "request": request, "token": token, "valido": False, "error": error,
        })
    return templates.TemplateResponse("reset_pass.html", {
        "request": request, "token": token, "valido": True, "error": error,
    })


@app.post("/reset-pass/{token}")
async def reset_pass_submit(
    request: Request,
    token: str,
    nueva_password: str = Form(...),
    confirmar_password: str = Form(...),
):
    info = password_reset.validar_token(token)
    if not info:
        return RedirectResponse(url=f"/reset-pass/{token}?error=expirado", status_code=303)

    if nueva_password != confirmar_password:
        return RedirectResponse(url=f"/reset-pass/{token}?error=no_coinciden", status_code=303)

    try:
        usuarios.cambiar_password(info.usuario_id, nueva_password)
    except usuarios.UsuarioError as e:
        return RedirectResponse(url=f"/reset-pass/{token}?error={str(e)[:60]}", status_code=303)

    password_reset.marcar_usado(token)
    password_reset.invalidar_tokens_de_usuario(info.usuario_id)

    # Notificación de seguridad al usuario afectado
    afectado = usuarios.obtener_por_id(info.usuario_id)
    if afectado:
        _notificar_password_cambiada(afectado, "Reset por email (link de recuperación)",
                                     _ip_cliente(request))

    return RedirectResponse(url="/login?reseteada=1", status_code=303)


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
@limiter.limit("5/minute")
async def procesar(
    request: Request,
    background_tasks: BackgroundTasks,
    archivo: UploadFile = File(...),
    bachiller:      str = Form(""),
    satje:          str = Form(""),
    setec_check:    str = Form(""),
    fiscalia_check: str = Form(""),
    forzar:         str = Form(""),
    jr_session: str | None = Cookie(None),
):
    u = _usuario_actual(jr_session)
    if not u:
        return _redirect_login()

    # Determinar tipo según checkboxes
    quiere_b        = bool(bachiller)
    quiere_s        = bool(satje)
    quiere_setec    = bool(setec_check)
    quiere_fiscalia = bool(fiscalia_check)

    if not quiere_b and not quiere_s and not quiere_setec and not quiere_fiscalia:
        return RedirectResponse(url="/?error=sin_seleccion", status_code=303)

    if quiere_b and quiere_s:
        tipo = "completo"
    elif quiere_b:
        tipo = "bachiller"
    elif quiere_s:
        tipo = "satje"
    else:
        tipo = "setec"   # solo SETEC (fiscalia se agrega como extra)

    # Leer Excel
    contenido = await archivo.read()
    items, errores = leer_cedulas(contenido)

    if errores:
        return RedirectResponse(url=f"/?error=excel", status_code=303)
    if not items:
        return RedirectResponse(url="/?error=vacio", status_code=303)

    # Crear job y disparar background task (con auditoria por usuario)
    job_id = crear_job(items, tipo, incluir_setec=quiere_setec,
                       incluir_fiscalia=quiere_fiscalia, usuario_id=u.id)
    background_tasks.add_task(ejecutar_job, job_id, items, tipo,
                               quiere_setec, quiere_fiscalia, u.id,
                               _to_bool(forzar))

    return RedirectResponse(url=f"/job/{job_id}", status_code=303)


# ── Búsqueda individual ──────────────────────────────────────────────────────

@app.post("/buscar", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def buscar_individual(
    request: Request,
    cedula:         str = Form(...),
    bachiller:      str = Form(""),
    satje:          str = Form(""),
    setec_check:    str = Form(""),
    fiscalia_check: str = Form(""),
    forzar:         str = Form(""),
    jr_session: str | None = Cookie(None),
):
    u = _usuario_actual(jr_session)
    if not u:
        return _redirect_login()

    cedula = (cedula or "").strip()
    if not cedula_valida_ec(cedula):
        return RedirectResponse(url="/?error=cedula_invalida", status_code=303)

    quiere_b        = bool(bachiller)
    quiere_s        = bool(satje)
    quiere_setec    = bool(setec_check)
    quiere_fiscalia = bool(fiscalia_check)
    if not quiere_b and not quiere_s and not quiere_setec and not quiere_fiscalia:
        return RedirectResponse(url="/?error=sin_seleccion", status_code=303)

    if quiere_b and quiere_s:
        tipo = "completo"
    elif quiere_b:
        tipo = "bachiller"
    elif quiere_s:
        tipo = "satje"
    else:
        tipo = "setec"

    # ── Cache ────────────────────────────────────────────────────────────────
    cached = None if forzar else buscar_cache(cedula, tipo)
    if cached:
        # Si se pide Fiscalia y el cache (viejo) no la tiene, consultarla ahora
        if quiere_fiscalia and cached.get("fiscalia") is None:
            raw_fisc = await consultar(cedula, tipo="fiscalia")
            cached["fiscalia"] = extraer_fiscalia(raw_fisc)
            try:
                registrar(cached, tipo, usuario_id=u.id)
            except Exception as _e:
                logger.warning("registrar() fallo (re-fetch fiscalia) ced=%s: %s", cedula, _e)
                capture_exception("buscar.registrar_refetch_fiscalia", _e, extra={"cedula": cedula})

        if quiere_b and quiere_s:
            cached["semaforo"] = _calcular_semaforo(
                cached.get("bachiller") or {},
                cached.get("satje") or {},
                "completo",
                fiscalia=cached.get("fiscalia"),
            )
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
        # Llamadas en paralelo: principal + setec + fiscalia
        _fr = _to_bool(forzar)  # propagar force_refresh al bg-api
        coros = [consultar(cedula, tipo=tipo, force_refresh=_fr)]
        coros.append(consultar(cedula, tipo="setec", force_refresh=_fr) if quiere_setec and tipo != "setec" else _noop_async())
        coros.append(consultar(cedula, tipo="fiscalia", force_refresh=_fr) if quiere_fiscalia else _noop_async())

        raw_results = await asyncio.gather(*coros)
        raw          = raw_results[0]
        raw_setec    = raw_results[1] if (quiere_setec and tipo != "setec") else (raw if tipo == "setec" else None)
        raw_fiscalia = raw_results[2] if quiere_fiscalia else None

        b        = extraer_bachiller(raw)       if quiere_b        else None
        s        = extraer_satje(raw)           if quiere_s        else None
        setec    = extraer_setec(raw_setec)     if raw_setec       else None
        fiscalia = extraer_fiscalia(raw_fiscalia) if raw_fiscalia   else None

        sem = ""
        if quiere_b and quiere_s:
            sem = _calcular_semaforo(b or {}, s or {}, "completo", fiscalia=fiscalia)

        nombre = ""
        for src in (b, s, setec):
            if src and src.get("nombre"):
                nombre = src["nombre"]
                break

        resultado = {
            "cedula":    cedula,
            "nombre":    nombre,
            "bachiller": b,
            "satje":     s,
            "setec":     setec,
            "fiscalia":  fiscalia,
            "semaforo":  sem,
        }
        try:
            registrar(resultado, tipo, usuario_id=u.id)
        except Exception as e:
            capture_exception("buscar.registrar_historial", e,
                              extra={"cedula": cedula, "tipo": tipo})

    return templates.TemplateResponse("resultado.html", {
        "request":   request,
        "resultado": resultado,
        "fecha":     datetime.now(_TZ_EC).strftime("%d/%m/%Y %H:%M"),
        "desde_cache": bool(resultado.get("_cache")),
    })


# ── Compliance LOPDP ─────────────────────────────────────────────────────────
# Derecho al olvido (Art. 14) + Limpieza periódica (Art. 12).
# Multa máxima por incumplimiento: $1,800,000 USD.

@app.post("/derecho-al-olvido")
async def derecho_al_olvido_endpoint(
    request: Request,
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
        audit_log.registrar(
            _usuario_actual(jr_session),
            "derecho_al_olvido",
            target=cedula,
            ip=_ip_cliente(request),
            motivo=motivo, n_hist=n_hist, n_ver=n_ver,
        )
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

    # Recalcular semáforo (incluir fiscalia si esta cacheada)
    if quiere_b and quiere_s:
        cached["semaforo"] = _calcular_semaforo(
            cached.get("bachiller") or {},
            cached.get("satje") or {},
            "completo",
            fiscalia=cached.get("fiscalia") or {},
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
    # Recalcular semáforo con lógica actual (incluir fiscalia si esta presente)
    if resultado.get("bachiller") and resultado.get("satje"):
        resultado["semaforo"] = _calcular_semaforo(
            resultado.get("bachiller") or {},
            resultado.get("satje") or {},
            "completo",
            fiscalia=resultado.get("fiscalia") or {},
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


@app.post("/historial/borrar-multiple")
async def borrar_multiples_historial(
    request: Request,
    ids: str = Form(""),
    jr_session: str | None = Cookie(None),
):
    """Borra varias entradas del historial. `ids` viene como CSV: 'id1,id2,id3'."""
    u = _usuario_actual(jr_session)
    if not u:
        return _redirect_login()
    lista_ids = [i for i in (ids or "").split(",") if i.strip()]
    n = borrar_multiples(lista_ids)
    audit_log.registrar(u, "historial_borrar_multiple",
                        ip=_ip_cliente(request), n_borradas=n, n_solicitadas=len(lista_ids))
    return RedirectResponse(url=f"/historial?msg=borradas&n={n}", status_code=303)


@app.post("/historial/cedula/{cedula}/nombre")
async def editar_nombre_cedula(
    cedula: str,
    nombre: str = Form(...),
    jr_session: str | None = Cookie(None),
):
    """Guarda el nombre manualmente para una cédula en el historial y cache."""
    if not _autenticado(jr_session):
        from fastapi.responses import JSONResponse
        return JSONResponse({"ok": False, "error": "no autenticado"}, status_code=401)
    ok = actualizar_nombre(cedula, nombre.strip())
    from fastapi.responses import JSONResponse
    return JSONResponse({"ok": ok})


@app.post("/historial/cedula/{cedula}/semaforo")
async def editar_semaforo_cedula(
    cedula: str,
    semaforo: str = Form(...),
    jr_session: str | None = Cookie(None),
):
    """Guarda manualmente el semáforo de una cédula. Sobrevive re-verificaciones."""
    if not _autenticado(jr_session):
        from fastapi.responses import JSONResponse
        return JSONResponse({"ok": False, "error": "no autenticado"}, status_code=401)
    ok = actualizar_semaforo(cedula, semaforo.strip())
    from fastapi.responses import JSONResponse
    return JSONResponse({"ok": ok})


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


# ════════════════════════════════════════════════════════════════════════════
# Multi-usuario: /perfil y /admin/usuarios
# ════════════════════════════════════════════════════════════════════════════

@app.get("/perfil", response_class=HTMLResponse)
async def perfil_form(
    request: Request,
    debe_cambiar: int = 0,
    ok: int = 0,
    error: str = "",
    jr_session: str | None = Cookie(None),
):
    u = _usuario_actual(jr_session)
    if not u:
        return _redirect_login()
    return templates.TemplateResponse("perfil.html", {
        "request":      request,
        "usuario":      u,
        "debe_cambiar": bool(debe_cambiar) or u.debe_cambiar_pass,
        "ok":           bool(ok),
        "error":        error,
    })


@app.post("/perfil/password")
async def perfil_cambiar_password(
    request: Request,
    nueva_password: str = Form(...),
    confirmar_password: str = Form(...),
    jr_session: str | None = Cookie(None),
):
    u = _usuario_actual(jr_session)
    if not u:
        return _redirect_login()
    if nueva_password != confirmar_password:
        return RedirectResponse(url="/perfil?error=no_coinciden", status_code=303)
    try:
        usuarios.cambiar_password(u.id, nueva_password)
    except usuarios.UsuarioError as e:
        return RedirectResponse(url=f"/perfil?error={str(e)[:60]}", status_code=303)
    _notificar_password_cambiada(u, "Cambio desde el perfil", _ip_cliente(request))
    return RedirectResponse(url="/perfil?ok=1", status_code=303)


@app.get("/admin/usuarios", response_class=HTMLResponse)
async def admin_usuarios_lista(
    request: Request,
    ok: str = "",
    error: str = "",
    jr_session: str | None = Cookie(None),
):
    u = _usuario_actual(jr_session)
    if not u:
        return _redirect_login()
    if u.rol != "admin":
        return RedirectResponse(url="/", status_code=303)
    lista = usuarios.listar(solo_activos=False)
    return templates.TemplateResponse("admin_usuarios.html", {
        "request":  request,
        "usuario":  u,
        "lista":    lista,
        "ok":       ok,
        "error":    error,
    })


@app.post("/admin/usuarios/crear")
async def admin_usuarios_crear(
    request: Request,
    email: str = Form(...),
    nombre: str = Form(...),
    password: str = Form(...),
    rol: str = Form("operador"),
    enviar_invitacion: str = Form(""),   # checkbox: "1" para enviar email
    jr_session: str | None = Cookie(None),
):
    u = _usuario_actual(jr_session)
    if not u or u.rol != "admin":
        return _redirect_login()
    try:
        nuevo = usuarios.crear_usuario(
            email=email, nombre=nombre, password=password, rol=rol,
            creado_por=u.id, debe_cambiar_pass=True,
        )
        audit_log.registrar(u, "usuario_creado", target=nuevo.email,
                            ip=_ip_cliente(request), nuevo_id=nuevo.id, rol=rol)
    except usuarios.UsuarioError as e:
        return RedirectResponse(url=f"/admin/usuarios?error={str(e)[:80]}", status_code=303)

    # Enviar email de onboarding con credenciales temporales si se pidió
    msg_ok = f"Creado+{nuevo.email}"
    if enviar_invitacion == "1":
        try:
            html = templates.get_template("email_bienvenida.html").render(
                nombre=nuevo.nombre,
                email=nuevo.email,
                password=password,
                rol=nuevo.rol,
                creador=u.nombre,
                link=f"{_base_url(request)}/login",
            )
            texto = (
                f"Hola {nuevo.nombre},\n\n"
                f"{u.nombre} te creó una cuenta en JR Verifica EC.\n\n"
                f"Email:      {nuevo.email}\n"
                f"Contraseña: {password}\n"
                f"Rol:        {nuevo.rol}\n\n"
                f"Ingresá a: {_base_url(request)}/login\n\n"
                f"Por seguridad, deberás cambiar la contraseña al ingresar."
            )
            enviado = enviar_email(
                to=nuevo.email,
                subject=f"Bienvenido a JR Verifica EC, {nuevo.nombre.split()[0]}",
                html=html,
                text=texto,
            )
            msg_ok = f"Creado+{nuevo.email}+(email+{'enviado' if enviado else 'fallo'})"
        except Exception as e:
            capture_exception("crear_usuario.email", e, extra={"email": nuevo.email})
            msg_ok = f"Creado+{nuevo.email}+(email+fallo)"

    return RedirectResponse(url=f"/admin/usuarios?ok={msg_ok}", status_code=303)


@app.post("/admin/usuarios/{user_id}/desactivar")
async def admin_usuarios_desactivar(
    request: Request,
    user_id: str,
    jr_session: str | None = Cookie(None),
):
    u = _usuario_actual(jr_session)
    if not u or u.rol != "admin":
        return _redirect_login()
    try:
        usuarios.desactivar(user_id, ejecutor_id=u.id)
        audit_log.registrar(u, "usuario_desactivado", target=user_id,
                            ip=_ip_cliente(request))
        return RedirectResponse(url="/admin/usuarios?ok=Desactivado", status_code=303)
    except usuarios.UsuarioError as e:
        return RedirectResponse(url=f"/admin/usuarios?error={str(e)[:80]}", status_code=303)


@app.post("/admin/usuarios/{user_id}/reactivar")
async def admin_usuarios_reactivar(
    request: Request,
    user_id: str,
    jr_session: str | None = Cookie(None),
):
    u = _usuario_actual(jr_session)
    if not u or u.rol != "admin":
        return _redirect_login()
    usuarios.reactivar(user_id)
    audit_log.registrar(u, "usuario_reactivado", target=user_id, ip=_ip_cliente(request))
    return RedirectResponse(url="/admin/usuarios?ok=Reactivado", status_code=303)


@app.post("/admin/usuarios/{user_id}/reset-password")
async def admin_usuarios_reset_password(
    request: Request,
    user_id: str,
    nueva_password: str = Form(...),
    jr_session: str | None = Cookie(None),
):
    u = _usuario_actual(jr_session)
    if not u or u.rol != "admin":
        return _redirect_login()
    try:
        usuarios.cambiar_password(user_id, nueva_password)
        # Forzar al usuario a cambiarla en su próximo login
        conn = usuarios._get_conn()
        with usuarios._write_lock:
            conn.execute(
                "UPDATE usuarios SET debe_cambiar_pass = 1 WHERE id = ?",
                (user_id,),
            )
    except usuarios.UsuarioError as e:
        return RedirectResponse(url=f"/admin/usuarios?error={str(e)[:80]}", status_code=303)

    # Notificación de seguridad al usuario afectado (no al admin que la reseteó)
    afectado = usuarios.obtener_por_id(user_id)
    if afectado:
        _notificar_password_cambiada(
            afectado,
            f"Reset por administrador ({u.nombre})",
            _ip_cliente(request),
        )
    audit_log.registrar(u, "password_reset_admin",
                        target=(afectado.email if afectado else user_id),
                        ip=_ip_cliente(request))
    return RedirectResponse(url="/admin/usuarios?ok=Password+reseteada", status_code=303)


@app.post("/admin/usuarios/{user_id}/cambiar-rol")
async def admin_usuarios_cambiar_rol(
    user_id: str,
    nuevo_rol: str = Form(...),
    jr_session: str | None = Cookie(None),
):
    u = _usuario_actual(jr_session)
    if not u or u.rol != "admin":
        return _redirect_login()
    try:
        usuarios.cambiar_rol(user_id, nuevo_rol)
        return RedirectResponse(url="/admin/usuarios?ok=Rol+actualizado", status_code=303)
    except usuarios.UsuarioError as e:
        return RedirectResponse(url=f"/admin/usuarios?error={str(e)[:80]}", status_code=303)


@app.post("/admin/test-email")
async def admin_test_email(
    request: Request,
    jr_session: str | None = Cookie(None),
):
    """
    Envía un email de prueba al admin logueado para validar que Resend
    (u otro driver) esté correctamente configurado.
    """
    u = _usuario_actual(jr_session)
    if not u or u.rol != "admin":
        return _redirect_login()

    from src.mailer import driver_activo_nombre
    driver = driver_activo_nombre()
    html = (
        f"<h2>Test de Email — JR Verifica EC</h2>"
        f"<p>Este email confirma que la configuración del mailer funciona correctamente.</p>"
        f"<ul>"
        f"<li><b>Driver activo:</b> {driver}</li>"
        f"<li><b>Enviado a:</b> {u.email}</li>"
        f"<li><b>Dominio:</b> {os.getenv('MAIL_FROM', '(no config)')}</li>"
        f"</ul>"
        f"<p style='color:#64748b;font-size:12px;'>Si recibís esto, podés crear operadores con email "
        f"de bienvenida y los usuarios pueden resetear su pass por email.</p>"
    )
    enviado = enviar_email(
        to=u.email,
        subject=f"[Test] JR Verifica EC — driver={driver}",
        html=html,
        text=f"Test email. Driver activo: {driver}. Enviado a: {u.email}",
    )
    msg = f"Email+enviado+via+{driver}+a+{u.email}" if enviado else "Fallo+envio+email"
    return RedirectResponse(url=f"/admin/usuarios?ok={msg}", status_code=303)


# ── Startup ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    logger.info("JR Verifica EC listo · BG_API_URL=%s · MAX_WORKERS=%s",
                os.getenv("BG_API_URL", "(no configurado)"),
                os.getenv("MAX_WORKERS", "3"))
