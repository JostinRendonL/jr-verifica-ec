"""
Compliance LOPDP — operaciones de retención y derecho al olvido.

LOPDP Ecuador (Ley Orgánica de Protección de Datos Personales):
- Art. 12 — debe haber plazo de conservación específico
- Art. 14 — titular tiene derecho ARCO (acceso, rectificación, cancelación, oposición)
- Art. 24 — antecedentes penales requieren justificación documentada
- Multa máxima: $1.800.000 USD

Este módulo expone:
    derecho_al_olvido(cedula)      → borra todo rastro de una cédula
    ejecutar_limpieza(meses=12)    → borra entradas más viejas que X meses
    estadisticas_compliance()      → cuántas entradas hay y cuántas se borrarían
"""
from __future__ import annotations

import os
import time
from typing import Any

from src.historial_sqlite import (
    borrar_por_cedula as _hist_borrar_cedula,
    borrar_antiguos as _hist_borrar_antiguos,
    total_entradas,
)
from src.verificaciones import (
    borrar_por_cedula as _ver_borrar_cedula,
    borrar_antiguos as _ver_borrar_antiguos,
    total as _ver_total,
)
from src.obs import capture_message, capture_exception


# Plazo de retención configurable (default 12 meses, LOPDP recomienda mínimo necesario)
RETENCION_MESES = int(os.getenv("RETENCION_MESES", "12"))


def derecho_al_olvido(cedula: str, motivo: str = "Solicitud del titular") -> dict[str, Any]:
    """
    LOPDP Art. 14 — borra TODO rastro de una cédula:
      1. Todas las entradas del historial (cache + auditoría)
      2. Todos los códigos de verificación (PDFs ya emitidos pierden validez del QR)

    Loguea la acción para evidencia legal de cumplimiento.

    Returns:
        {
            "cedula":                str,
            "historial_borrado":     int,  # entradas del historial
            "verificaciones_borradas": int,
            "timestamp":             int,
            "motivo":                str,
        }
    """
    cedula = (cedula or "").strip()
    if not cedula:
        return {"error": "cedula vacía", "cedula": "", "historial_borrado": 0,
                "verificaciones_borradas": 0}

    try:
        n_hist = _hist_borrar_cedula(cedula)
        n_ver  = _ver_borrar_cedula(cedula)
        ts = int(time.time())

        # Log de auditoría — esto SIEMPRE debe quedar (incluso el borrado tiene rastro
        # del evento, sin datos personales del titular más allá de la cédula).
        capture_message(
            "LOPDP.derecho_al_olvido",
            extra={
                "cedula":                cedula,
                "historial_borrado":     n_hist,
                "verificaciones_borradas": n_ver,
                "motivo":                motivo,
                "timestamp":             ts,
            },
            level="info",
        )
        print(f"[LOPDP] derecho_al_olvido cedula={cedula} hist={n_hist} ver={n_ver} motivo='{motivo}'")

        return {
            "cedula":                  cedula,
            "historial_borrado":       n_hist,
            "verificaciones_borradas": n_ver,
            "timestamp":               ts,
            "motivo":                  motivo,
            "ok":                      True,
        }
    except Exception as e:
        capture_exception("LOPDP.derecho_al_olvido", e, extra={"cedula": cedula})
        return {"cedula": cedula, "error": str(e)[:200], "ok": False,
                "historial_borrado": 0, "verificaciones_borradas": 0}


def ejecutar_limpieza(meses: int | None = None) -> dict[str, Any]:
    """
    LOPDP Art. 12 — borra todas las entradas más viejas que `meses` meses.
    Pensado para ejecutarse periódicamente (cron semanal).

    Returns:
        {
            "meses":                  int,
            "historial_borrado":      int,
            "verificaciones_borradas": int,
            "timestamp":              int,
        }
    """
    meses_efectivos = meses if meses is not None else RETENCION_MESES

    try:
        n_hist = _hist_borrar_antiguos(meses_efectivos)
        n_ver  = _ver_borrar_antiguos(meses_efectivos)
        ts = int(time.time())

        if n_hist > 0 or n_ver > 0:
            capture_message(
                "LOPDP.limpieza_periodica",
                extra={
                    "meses":                  meses_efectivos,
                    "historial_borrado":      n_hist,
                    "verificaciones_borradas": n_ver,
                    "timestamp":              ts,
                },
                level="info",
            )
        print(f"[LOPDP] limpieza_periodica meses={meses_efectivos} hist={n_hist} ver={n_ver}")

        return {
            "meses":                   meses_efectivos,
            "historial_borrado":       n_hist,
            "verificaciones_borradas": n_ver,
            "timestamp":               ts,
            "ok":                      True,
        }
    except Exception as e:
        capture_exception("LOPDP.limpieza_periodica", e, extra={"meses": meses_efectivos})
        return {"meses": meses_efectivos, "error": str(e)[:200], "ok": False,
                "historial_borrado": 0, "verificaciones_borradas": 0}


def estadisticas_compliance() -> dict[str, Any]:
    """Resumen del estado actual para el panel de admin."""
    # Estado del scheduler — import diferido para evitar ciclo
    scheduler_info: dict[str, Any] = {"activo": False, "proxima_limpieza": None}
    try:
        from src import scheduler as _sch
        if _sch._scheduler is not None and _sch._scheduler.running:
            scheduler_info["activo"] = True
            job = _sch._scheduler.get_job("limpieza_lopdp_semanal")
            if job and job.next_run_time:
                scheduler_info["proxima_limpieza"] = job.next_run_time.isoformat()
                scheduler_info["job_id"]           = job.id
                scheduler_info["job_name"]         = job.name
    except Exception as e:
        scheduler_info["error"] = str(e)[:120]

    return {
        "retencion_meses":        RETENCION_MESES,
        "total_historial":        total_entradas(),
        "total_verificaciones":   _ver_total(),
        "timestamp":              int(time.time()),
        "scheduler":              scheduler_info,
    }
