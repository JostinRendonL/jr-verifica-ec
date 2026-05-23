"""Procesador batch con concurrencia limitada."""
import os
import asyncio
import uuid
import time
from typing import Literal

from src.bg_client import consultar, extraer_bachiller, extraer_satje

MAX_WORKERS = int(os.getenv("MAX_WORKERS", "3"))

# Store in-memory de jobs (suficiente para 1 worker)
_jobs: dict[str, dict] = {}


def crear_job(cedulas: list[str], tipo: str) -> str:
    """Crea un job nuevo y retorna su ID."""
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {
        "id":          job_id,
        "tipo":        tipo,
        "total":       len(cedulas),
        "procesados":  0,
        "estado":      "pendiente",
        "iniciado":    time.time(),
        "terminado":   None,
        "resultados":  [],
        "excel_bytes": None,
    }
    return job_id


def obtener_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


def _calcular_semaforo(bachiller: dict, satje: dict, tipo: str) -> str:
    """Calcula semáforo si se piden ambos checks."""
    if tipo != "completo":
        return ""

    # ROJO: procesos judiciales como demandado
    if satje.get("estado") == "TIENE_PROCESOS" and satje.get("total_demandado", 0) > 0:
        return "🔴 ROJO"
    # GRIS: error en alguno
    if bachiller.get("estado") == "ERROR" or satje.get("estado") == "ERROR":
        return "⚪ GRIS"
    # AMARILLO: sin título o causas como actor
    if bachiller.get("estado") != "ENCONTRADO" or satje.get("total_actor", 0) > 0:
        return "🟡 AMARILLO"
    # VERDE: bachiller confirmado, sin procesos
    return "🟢 VERDE"


async def _procesar_una(cedula: str, tipo: str, sem: asyncio.Semaphore) -> dict:
    """Procesa una sola cédula con semáforo de concurrencia."""
    async with sem:
        if tipo == "bachiller":
            raw = await consultar(cedula, tipo="bachiller")
            return {
                "cedula":    cedula,
                "bachiller": extraer_bachiller(raw),
            }
        if tipo == "satje":
            raw = await consultar(cedula, tipo="satje")
            return {
                "cedula": cedula,
                "satje":  extraer_satje(raw),
            }
        # completo: pedimos ambos en una sola llamada al endpoint /completo
        raw = await consultar(cedula, tipo="completo")
        b = extraer_bachiller(raw)
        s = extraer_satje(raw)
        return {
            "cedula":    cedula,
            "bachiller": b,
            "satje":     s,
            "semaforo":  _calcular_semaforo(b, s, "completo"),
        }


async def ejecutar_job(job_id: str, cedulas: list[str], tipo: str) -> None:
    """
    Ejecuta el job en background, actualizando _jobs[job_id]['procesados']
    en cada cédula completada.
    """
    from src.excel_io import generar_excel_resultados

    job = _jobs[job_id]
    job["estado"] = "procesando"

    sem = asyncio.Semaphore(MAX_WORKERS)

    async def _task(c: str):
        r = await _procesar_una(c, tipo, sem)
        job["resultados"].append(r)
        job["procesados"] = len(job["resultados"])
        return r

    try:
        await asyncio.gather(*[_task(c) for c in cedulas])

        # Ordenar resultados por orden original de cédulas
        orden = {c: i for i, c in enumerate(cedulas)}
        job["resultados"].sort(key=lambda r: orden.get(r.get("cedula", ""), 9999))

        # Generar Excel
        job["excel_bytes"] = generar_excel_resultados(job["resultados"], tipo)
        job["estado"]      = "completado"
        job["terminado"]   = time.time()
    except Exception as e:
        job["estado"]    = "error"
        job["error"]     = f"{type(e).__name__}: {str(e)[:300]}"
        job["terminado"] = time.time()
