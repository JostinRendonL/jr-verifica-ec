"""Procesador batch con concurrencia limitada."""
import os
import asyncio
import uuid
import time
from typing import Literal

from src.bg_client import consultar, extraer_bachiller, extraer_satje, extraer_setec
from src.historial import buscar_cache, registrar

MAX_WORKERS = int(os.getenv("MAX_WORKERS", "3"))

# Store in-memory de jobs (suficiente para 1 worker)
_jobs: dict[str, dict] = {}


def crear_job(items: list[dict], tipo: str, incluir_setec: bool = False) -> str:
    """Crea un job nuevo y retorna su ID. items = [{'cedula': '...', 'nombre': '...'}]"""
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {
        "id":            job_id,
        "tipo":          tipo,
        "incluir_setec": incluir_setec,
        "total":         len(items),
        "procesados":    0,
        "estado":        "pendiente",
        "iniciado":      time.time(),
        "terminado":     None,
        "resultados":    [],
        "excel_bytes":   None,
    }
    return job_id


def obtener_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


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
    """Detecta si entre los delitos hay alguno considerado grave."""
    delitos = satje.get("delitos", []) or []
    texto = " ".join(d.upper() for d in delitos)
    return any(g in texto for g in DELITOS_GRAVES)


def _calcular_semaforo(bachiller: dict, satje: dict, tipo: str) -> str:
    """
    Calcula nivel de riesgo si se piden ambos checks.

    Niveles:
      🟢 APTO         — Bachiller confirmado + sin procesos
      🟡 OBSERVACIÓN  — Sin título oficial, O procesos como actor (víctima/demandante)
      🔴 RECHAZAR     — Procesos como demandado (sin delitos graves)
      🚨 CRÍTICO      — Delitos graves detectados (homicidio, narcos, etc)
      ⚪ SIN DATOS    — Error en alguna consulta
    """
    if tipo != "completo":
        return ""

    # ⚪ SIN DATOS — error en algo
    if bachiller.get("estado") == "ERROR" or satje.get("estado") == "ERROR":
        return "⚪ SIN DATOS"

    # 🚨 CRÍTICO o 🔴 RECHAZAR — procesos como demandado
    if satje.get("estado") == "TIENE_PROCESOS" and satje.get("total_demandado", 0) > 0:
        if _tiene_delitos_graves(satje):
            return "🚨 CRÍTICO"
        return "🔴 RECHAZAR"

    # 🟡 OBSERVACIÓN — sin título o procesos como actor
    if bachiller.get("estado") != "ENCONTRADO" or satje.get("total_actor", 0) > 0:
        return "🟡 OBSERVACIÓN"

    # 🟢 APTO
    return "🟢 APTO"


async def _procesar_una(item: dict, tipo: str, incluir_setec: bool, sem: asyncio.Semaphore) -> dict:
    """Procesa una sola cédula con semáforo de concurrencia. Usa caché si está disponible."""
    cedula = item["cedula"]
    nombre_input = item.get("nombre", "")

    # ── Cache hit ────────────────────────────────────────────────────────────
    cached = buscar_cache(cedula, tipo)
    if cached is not None:
        # Recalcular el semáforo con la lógica actual (no usar el guardado)
        if tipo == "completo":
            cached["semaforo"] = _calcular_semaforo(
                cached.get("bachiller") or {},
                cached.get("satje") or {},
                "completo",
            )
        # Si pidieron SETEC y el cache no lo tiene, hacer la llamada por separado
        if incluir_setec and not cached.get("setec"):
            async with sem:
                raw_st = await consultar(cedula, tipo="setec")
            cached["setec"] = extraer_setec(raw_st)
            try:
                registrar(cached, tipo)
            except Exception:
                pass
        return {**cached, "_cache": True}

    async with sem:
        # Si quieren SETEC junto con otra cosa, llamadas paralelas
        if incluir_setec and tipo != "setec":
            raw_main, raw_setec = await asyncio.gather(
                consultar(cedula, tipo=tipo),
                consultar(cedula, tipo="setec"),
            )
        elif tipo == "setec":
            raw_main  = await consultar(cedula, tipo="setec")
            raw_setec = raw_main
        else:
            raw_main  = await consultar(cedula, tipo=tipo)
            raw_setec = None

        if tipo == "bachiller":
            b = extraer_bachiller(raw_main)
            resultado = {
                "cedula":    cedula,
                "nombre":    b.get("nombre", "") or nombre_input,
                "bachiller": b,
            }
        elif tipo == "satje":
            s = extraer_satje(raw_main)
            resultado = {
                "cedula": cedula,
                "nombre": s.get("nombre", "") or nombre_input,
                "satje":  s,
            }
        elif tipo == "setec":
            setec = extraer_setec(raw_main)
            resultado = {
                "cedula": cedula,
                "nombre": nombre_input,
                "setec":  setec,
            }
        else:
            # completo: bachiller + satje. SETEC viene aparte si fue solicitado.
            b = extraer_bachiller(raw_main)
            s = extraer_satje(raw_main)
            resultado = {
                "cedula":    cedula,
                "nombre":    b.get("nombre", "") or s.get("nombre", "") or nombre_input,
                "bachiller": b,
                "satje":     s,
                "semaforo":  _calcular_semaforo(b, s, "completo"),
            }

        # Agregar SETEC al resultado si fue solicitado y el tipo no era "setec" puro
        if incluir_setec and tipo != "setec" and raw_setec is not None:
            resultado["setec"] = extraer_setec(raw_setec)

    # Registrar en historial+cache
    try:
        registrar(resultado, tipo)
    except Exception as e:
        print(f"[processor] no se pudo registrar en historial: {e}")

    return resultado


async def ejecutar_job(job_id: str, items: list[dict], tipo: str, incluir_setec: bool = False) -> None:
    """
    Ejecuta el job en background, actualizando _jobs[job_id]['procesados']
    en cada cédula completada.
    """
    from src.excel_io import generar_excel_resultados

    job = _jobs[job_id]
    job["estado"] = "procesando"

    sem = asyncio.Semaphore(MAX_WORKERS)

    async def _task(it: dict):
        r = await _procesar_una(it, tipo, incluir_setec, sem)
        job["resultados"].append(r)
        job["procesados"] = len(job["resultados"])
        return r

    try:
        await asyncio.gather(*[_task(it) for it in items])

        # Ordenar resultados por orden original
        orden = {it["cedula"]: i for i, it in enumerate(items)}
        job["resultados"].sort(key=lambda r: orden.get(r.get("cedula", ""), 9999))

        # Generar Excel
        job["excel_bytes"] = generar_excel_resultados(job["resultados"], tipo, incluir_setec)
        job["estado"]      = "completado"
        job["terminado"]   = time.time()
    except Exception as e:
        job["estado"]    = "error"
        job["error"]     = f"{type(e).__name__}: {str(e)[:300]}"
        job["terminado"] = time.time()
