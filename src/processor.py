"""Procesador batch con concurrencia limitada."""
import os
import asyncio
import uuid
import time
from typing import Literal

from src.bg_client import consultar, extraer_bachiller, extraer_satje, extraer_setec, extraer_fiscalia
from src.historial_sqlite import buscar_cache, registrar, obtener_nombre_guardado, obtener_semaforo_manual
from src.obs import capture_exception

MAX_WORKERS = int(os.getenv("MAX_WORKERS", "3"))

# Store in-memory de jobs (suficiente para 1 worker)
_jobs: dict[str, dict] = {}


async def _noop() -> None:
    """Coroutine vacia — placeholder para gather cuando un modulo no se solicita."""
    return None


def crear_job(items: list[dict], tipo: str, incluir_setec: bool = False,
              incluir_fiscalia: bool = False,
              usuario_id: str | None = None) -> str:
    """Crea un job nuevo y retorna su ID. items = [{'cedula': '...', 'nombre': '...'}]"""
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {
        "id":               job_id,
        "tipo":             tipo,
        "incluir_setec":    incluir_setec,
        "incluir_fiscalia": incluir_fiscalia,
        "usuario_id":       usuario_id,
        "total":            len(items),
        "procesados":       0,
        "estado":           "pendiente",
        "iniciado":         time.time(),
        "terminado":        None,
        "resultados":       [],
        "excel_bytes":      None,
    }
    return job_id


def obtener_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


# Palabras clave para identificar causas de pensión alimenticia.
# Estas causas NO descalifican laboralmente (regla de negocio):
# se degradan de RECHAZAR → OBSERVACIÓN cuando son las únicas presentes.
PALABRAS_ALIMENTOS = (
    "ALIMENTOS",
    "PENSION ALIMENTICIA",
    "PENSIÓN ALIMENTICIA",
    "FIJACION DE PENSION",
    "FIJACIÓN DE PENSIÓN",
)


def _es_causa_de_alimentos(causa: dict) -> bool:
    """True si la causa es por pensión alimenticia."""
    delito  = (causa.get("delito") or "").upper()
    materia = (causa.get("materia") or "").upper()
    return any(p in delito or p in materia for p in PALABRAS_ALIMENTOS)


def _solo_alimentos(satje: dict) -> bool:
    """True si TODAS las causas (demandado + actor) son por alimentos."""
    todas = (satje.get("causas_demandado") or []) + (satje.get("causas_actor") or [])
    return bool(todas) and all(_es_causa_de_alimentos(c) for c in todas)


# Delitos que disparan el nivel CRÍTICO (escala de gravedad alta)
DELITOS_GRAVES = [
    "ASESINATO", "HOMICIDIO", "FEMICIDIO", "PARRICIDIO", "SICARIATO",
    "VIOLACION", "VIOLACIÓN", "ABUSO SEXUAL", "ESTUPRO",
    "SECUESTRO", "EXTORSION", "EXTORSIÓN", "PLAGIO",
    "ROBO", "ASALTO",
    "NARCOTRAFICO", "NARCOTRÁFICO", "DROGAS", "ESTUPEFACIENTES",
    "DELINCUENCIA ORGANIZADA",
    "TERRORISMO",
    "TRATA DE PERSONAS",
    "LAVADO DE ACTIVOS",
    "TENENCIA DE ARMAS", "TENENCIA ILEGAL",
    "PECULADO", "ENRIQUECIMIENTO ILICITO",
]


def _tiene_delitos_graves(satje: dict) -> bool:
    """LEGACY — Detecta si entre los delitos hay alguno considerado grave.
    Mantenido por compatibilidad. La nueva lógica usa clasificar_lista_delitos."""
    delitos = satje.get("delitos", []) or []
    texto = " ".join(d.upper() for d in delitos)
    return any(g in texto for g in DELITOS_GRAVES)


def _tiene_delitos_graves_fiscalia(fiscalia: dict) -> bool:
    """LEGACY — ídem para Fiscalía."""
    delitos = fiscalia.get("delitos", []) or []
    texto = " ".join(d.upper() for d in delitos)
    return any(g in texto for g in DELITOS_GRAVES)


def _calcular_semaforo(bachiller: dict, satje: dict, tipo: str,
                       fiscalia: dict | None = None) -> str:
    """
    Calcula nivel de riesgo usando clasificación de 3 niveles (Fase 3).

    Niveles:
      🚨 CRÍTICO      — Algún delito en lista CRITICO (homicidio, narcos, violación, etc)
      🔴 RECHAZAR     — Algún delito en lista RECHAZAR (robo, estafa, lesiones, etc)
                        O delito desconocido como demandado/sospechoso (conservador)
      🟡 OBSERVACIÓN  — Solo delitos en lista OBSERVACION (alimentos, divorcio, etc)
                        O sin título oficial, O procesos como actor,
                        O denunciante en Fiscalía, O rol DESCONOCIDO en Fiscalía
      🟢 APTO         — Bachiller confirmado + sin procesos
      ⚪ SIN DATOS    — Error en Bachiller o SATJE
    """
    from src.delitos_clasificacion import clasificar_lista_delitos

    if tipo != "completo":
        return ""

    # ⚪ SIN DATOS — error en algo
    if bachiller.get("estado") == "ERROR" or satje.get("estado") == "ERROR":
        return "⚪ SIN DATOS"

    # Recolectar TODOS los delitos donde la persona aparece como demandado/sospechoso
    delitos_serios = []
    # SATJE — solo causas como demandado (no actor)
    if satje.get("estado") == "TIENE_PROCESOS" and satje.get("total_demandado", 0) > 0:
        for causa in satje.get("causas_demandado") or []:
            d = causa.get("delito") or ""
            if d:
                delitos_serios.append(d)
        # Si no hay causas_demandado pero sí total_demandado, usar lista delitos legacy
        if not delitos_serios:
            for d in satje.get("delitos") or []:
                if d:
                    delitos_serios.append(d)
    # Fiscalía — solo si sospechoso
    if fiscalia and fiscalia.get("como_sospechoso", 0) > 0:
        for d in fiscalia.get("delitos") or []:
            if d:
                delitos_serios.append(d)

    # Clasificar el peor delito encontrado
    nivel = clasificar_lista_delitos(delitos_serios)

    if nivel == "CRITICO":
        return "🚨 CRÍTICO"
    if nivel == "RECHAZAR":
        return "🔴 RECHAZAR"
    if nivel == "OBSERVACION":
        # Solo delitos personales/civiles → OBSERVACIÓN (no rechazar)
        return "🟡 OBSERVACIÓN"

    # No hay delitos serios. Verificar condiciones secundarias para OBSERVACIÓN:
    if bachiller.get("estado") != "ENCONTRADO":
        return "🟡 OBSERVACIÓN"
    if satje.get("total_actor", 0) > 0:
        return "🟡 OBSERVACIÓN"
    if fiscalia and fiscalia.get("como_denunciante", 0) > 0:
        return "🟡 OBSERVACIÓN"

    # 🟢 APTO — Bachiller OK + sin procesos como demandado + sin antecedentes Fiscalía
    return "🟢 APTO"


async def _procesar_una(item: dict, tipo: str, incluir_setec: bool, sem: asyncio.Semaphore,
                        usuario_id: str | None = None,
                        incluir_fiscalia: bool = False) -> dict:
    """Procesa una sola cédula con semáforo de concurrencia. Usa caché si está disponible."""
    cedula = item["cedula"]
    nombre_input = item.get("nombre", "")

    # ── Cache hit ────────────────────────────────────────────────────────────
    cached = buscar_cache(cedula, tipo)
    if cached is not None:
        # Recalcular el semáforo con la lógica actual (no usar el guardado),
        # EXCEPTO si el semáforo fue editado manualmente — en ese caso se preserva.
        # IMPORTANTE: pasar fiscalia tambien — si el cache tiene fiscalia con
        # SOSPECHOSO, el semaforo correcto es RECHAZAR/CRITICO, NO APTO.
        if tipo == "completo" and not cached.get("semaforo_manual"):
            cached["semaforo"] = _calcular_semaforo(
                cached.get("bachiller") or {},
                cached.get("satje") or {},
                "completo",
                fiscalia=cached.get("fiscalia") or {},
            )
        # Si pidieron SETEC y el cache no lo tiene, hacer la llamada por separado
        if incluir_setec and not cached.get("setec"):
            async with sem:
                raw_st = await consultar(cedula, tipo="setec")
            cached["setec"] = extraer_setec(raw_st)
            try:
                registrar(cached, tipo, usuario_id=usuario_id)
            except Exception:
                pass

        # Si pidieron Fiscalia y el cache no la tiene O esta cacheada con error,
        # re-fetch desde bg-api. Importante: los errores transitorios (Incapsula,
        # proxy caido, etc) no deben quedar pegados en cache para siempre.
        cached_fi = cached.get("fiscalia") or {}
        fi_ausente = not cached_fi
        fi_con_error = cached_fi.get("estado") == "ERROR"
        if incluir_fiscalia and (fi_ausente or fi_con_error):
            async with sem:
                raw_f = await consultar(cedula, tipo="fiscalia")
            cached["fiscalia"] = extraer_fiscalia(raw_f)
            if tipo == "completo" and not cached.get("semaforo_manual"):
                cached["semaforo"] = _calcular_semaforo(
                    cached.get("bachiller") or {},
                    cached.get("satje") or {},
                    "completo",
                    fiscalia=cached["fiscalia"],
                )
            try:
                registrar(cached, tipo, usuario_id=usuario_id)
            except Exception:
                pass

        # Si Bachiller o SATJE están cacheados con ERROR, re-fetch desde bg-api.
        # Mismo patrón que la lógica de Fiscalía — errores transitorios (proxy agotado,
        # captcha fallido, timeout) no deben quedar pegados en cache 24h.
        if tipo == "completo":
            b_con_error = (cached.get("bachiller") or {}).get("estado") == "ERROR"
            s_con_error = (cached.get("satje") or {}).get("estado") == "ERROR"
            if b_con_error or s_con_error:
                async with sem:
                    raw_main = await consultar(cedula, tipo="completo")
                if b_con_error:
                    cached["bachiller"] = extraer_bachiller(raw_main)
                if s_con_error:
                    cached["satje"] = extraer_satje(raw_main)
                if not cached.get("semaforo_manual"):
                    cached["semaforo"] = _calcular_semaforo(
                        cached.get("bachiller") or {},
                        cached.get("satje") or {},
                        "completo",
                        fiscalia=cached.get("fiscalia") or {},
                    )
                try:
                    registrar(cached, tipo, usuario_id=usuario_id)
                except Exception:
                    pass

        # Auto-relleno de nombre faltante (cache viejo del schema anterior a SETEC.nombre):
        # Si NO hay nombre cacheado Y el SETEC cacheado dice TIENE_CERTIFICADOS pero no
        # trae nombre, re-fetch SOLO el SETEC para rescatar el nombre desde la tabla.
        # Esto repara cache antiguo automáticamente sin que el usuario tenga que
        # forzar consulta ni esperar el TTL de 24h.
        if not cached.get("nombre"):
            st_old = cached.get("setec") or {}
            if st_old.get("estado") == "TIENE_CERTIFICADOS" and not st_old.get("nombre"):
                async with sem:
                    raw_st2 = await consultar(cedula, tipo="setec")
                new_st = extraer_setec(raw_st2)
                cached["setec"] = new_st
                if new_st.get("nombre"):
                    cached["nombre"] = new_st["nombre"]
                try:
                    registrar(cached, tipo, usuario_id=usuario_id)
                except Exception:
                    pass

        # Prioridad de nombre: Excel > cache > SETEC inline > nombre guardado en DB.
        if nombre_input:
            cached["nombre"] = nombre_input
        elif not cached.get("nombre"):
            st = cached.get("setec") or {}
            if st.get("nombre"):
                cached["nombre"] = st["nombre"]
            else:
                # Fallback: nombre editado manualmente en una sesión anterior
                nombre_db = obtener_nombre_guardado(cedula)
                if nombre_db:
                    cached["nombre"] = nombre_db
        return {**cached, "_cache": True}

    async with sem:
        # Construir lista de coroutines a ejecutar en paralelo
        coros = [consultar(cedula, tipo=tipo)]
        if incluir_setec and tipo != "setec":
            coros.append(consultar(cedula, tipo="setec"))
        else:
            coros.append(asyncio.coroutine(lambda: None)() if False else _noop())
        if incluir_fiscalia:
            coros.append(consultar(cedula, tipo="fiscalia"))
        else:
            coros.append(_noop())

        raw_results = await asyncio.gather(*coros, return_exceptions=True)
        raw_main    = raw_results[0] if not isinstance(raw_results[0], Exception) else {"ok": False, "error": str(raw_results[0])}
        raw_setec   = raw_results[1] if (incluir_setec and tipo != "setec") else None
        raw_fiscalia = raw_results[2] if incluir_fiscalia else None

        # Si tipo es setec, raw_main ES la respuesta de setec
        if tipo == "setec":
            raw_setec = raw_main

        # Extraer datos
        setec_data   = None
        fiscalia_data = None

        if tipo == "setec":
            setec_data = extraer_setec(raw_main)
        elif incluir_setec and raw_setec is not None and not isinstance(raw_setec, Exception):
            setec_data = extraer_setec(raw_setec)

        if incluir_fiscalia and raw_fiscalia is not None and not isinstance(raw_fiscalia, Exception):
            fiscalia_data = extraer_fiscalia(raw_fiscalia)

        # Prioridad de nombre UNIFICADA:
        #   1) Excel input  2) Bachiller  3) SATJE  4) SETEC  5) Fiscalía  6) DB manual
        def _elegir_nombre(b=None, s=None, st=None, fi=None):
            if nombre_input:
                return nombre_input
            for src in (b, s, st, fi):
                if src and src.get("nombre"):
                    return src["nombre"]
            # Fallback: nombre editado manualmente en historial (re-verificación)
            return obtener_nombre_guardado(cedula)

        # Semáforo manual previo — si existía, preservarlo incluso tras re-fetch
        _semaforo_manual_previo = obtener_semaforo_manual(cedula)

        if tipo == "bachiller":
            b = extraer_bachiller(raw_main)
            resultado = {
                "cedula":    cedula,
                "nombre":    _elegir_nombre(b=b, st=setec_data, fi=fiscalia_data),
                "bachiller": b,
            }
        elif tipo == "satje":
            s = extraer_satje(raw_main)
            resultado = {
                "cedula": cedula,
                "nombre": _elegir_nombre(s=s, st=setec_data, fi=fiscalia_data),
                "satje":  s,
            }
        elif tipo == "setec":
            resultado = {
                "cedula": cedula,
                "nombre": _elegir_nombre(st=setec_data, fi=fiscalia_data),
                "setec":  setec_data,
            }
        else:
            # completo: bachiller + satje (+ fiscalia si se pidio)
            b = extraer_bachiller(raw_main)
            s = extraer_satje(raw_main)
            _sem_calculado = _calcular_semaforo(b, s, "completo", fiscalia=fiscalia_data)
            resultado = {
                "cedula":    cedula,
                "nombre":    _elegir_nombre(b=b, s=s, st=setec_data, fi=fiscalia_data),
                "bachiller": b,
                "satje":     s,
                # Si el usuario editó el semáforo manualmente, preservarlo
                "semaforo":          _semaforo_manual_previo or _sem_calculado,
                "semaforo_manual":   bool(_semaforo_manual_previo),
            }

        # Agregar módulos opcionales al resultado
        if incluir_setec and tipo != "setec" and setec_data is not None:
            resultado["setec"] = setec_data
        if incluir_fiscalia and fiscalia_data is not None:
            resultado["fiscalia"] = fiscalia_data

    # Registrar en historial+cache
    try:
        registrar(resultado, tipo, usuario_id=usuario_id)
    except Exception as e:
        capture_exception("processor.registrar", e,
                          extra={"cedula": cedula, "tipo": tipo})

    return resultado


async def ejecutar_job(job_id: str, items: list[dict], tipo: str,
                       incluir_setec: bool = False,
                       incluir_fiscalia: bool = False,
                       usuario_id: str | None = None) -> None:
    """
    Ejecuta el job en background, actualizando _jobs[job_id]['procesados']
    en cada cédula completada.
    """
    from src.excel_io import generar_excel_resultados

    job = _jobs[job_id]
    job["estado"] = "procesando"
    if usuario_id is None:
        usuario_id = job.get("usuario_id")
    if not incluir_fiscalia:
        incluir_fiscalia = job.get("incluir_fiscalia", False)

    sem = asyncio.Semaphore(MAX_WORKERS)

    async def _task(it: dict):
        r = await _procesar_una(it, tipo, incluir_setec, sem,
                                usuario_id=usuario_id,
                                incluir_fiscalia=incluir_fiscalia)
        job["resultados"].append(r)
        job["procesados"] = len(job["resultados"])
        return r

    try:
        await asyncio.gather(*[_task(it) for it in items])

        # Ordenar resultados por orden original
        orden = {it["cedula"]: i for i, it in enumerate(items)}
        job["resultados"].sort(key=lambda r: orden.get(r.get("cedula", ""), 9999))

        # Generar Excel
        job["excel_bytes"] = generar_excel_resultados(
            job["resultados"], tipo, incluir_setec,
            incluir_fiscalia=incluir_fiscalia,
        )
        job["estado"]      = "completado"
        job["terminado"]   = time.time()
    except Exception as e:
        job["estado"]    = "error"
        job["error"]     = f"{type(e).__name__}: {str(e)[:300]}"
        job["terminado"] = time.time()
        capture_exception("processor.ejecutar_job", e,
                          extra={"job_id": job_id, "tipo": tipo,
                                 "items_count": len(items),
                                 "procesados": job["procesados"]})
