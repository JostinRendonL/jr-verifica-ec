"""
Scheduler — tareas periódicas con APScheduler.

Corre dentro del proceso de FastAPI (background thread). Sin dependencias
externas tipo Easypanel Scheduled Tasks ni cron del sistema.

Tareas actualmente configuradas:
- Limpieza LOPDP semanal (domingo 03:00): borra entradas >RETENCION_MESES.

Var de entorno:
    SCHEDULER_ENABLED  — '1' por defecto. '0' para desactivar (útil en tests).
    LIMPIEZA_CRON_HORA — hora del día (0-23, default 3).
    LIMPIEZA_CRON_DIA  — día de la semana (0=lun..6=dom, default 6 = domingo).
"""
from __future__ import annotations

import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.compliance import ejecutar_limpieza
from src.obs import capture_exception, capture_message
from src import password_reset


_scheduler: BackgroundScheduler | None = None


def _tarea_limpieza_lopdp() -> None:
    """Wrapper que ejecuta la limpieza y captura cualquier error."""
    try:
        resultado = ejecutar_limpieza()
        if resultado.get("ok"):
            capture_message(
                "scheduler.limpieza_lopdp.ok",
                extra={
                    "historial_borrado":      resultado.get("historial_borrado", 0),
                    "verificaciones_borradas": resultado.get("verificaciones_borradas", 0),
                    "meses":                  resultado.get("meses"),
                },
                level="info",
            )
        else:
            capture_message(
                "scheduler.limpieza_lopdp.fallo",
                extra={"error": resultado.get("error", "desconocido")},
                level="warning",
            )
    except Exception as e:
        capture_exception("scheduler.limpieza_lopdp", e)


def _tarea_limpieza_tokens_reset() -> None:
    """Borra tokens de reset de password expirados o usados hace > 7 días.

    Corre diariamente para mantener la tabla password_resets pequeña.
    """
    try:
        n = password_reset.limpiar_expirados()
        if n > 0:
            print(f"[scheduler] limpieza tokens reset: {n} borrados")
            capture_message(
                "scheduler.limpieza_tokens.ok",
                extra={"borrados": n},
                level="info",
            )
    except Exception as e:
        capture_exception("scheduler.limpieza_tokens", e)


def iniciar_scheduler() -> None:
    """Lanza el scheduler en background. Idempotente."""
    global _scheduler

    if os.getenv("SCHEDULER_ENABLED", "1") != "1":
        print("[scheduler] desactivado por SCHEDULER_ENABLED=0")
        return

    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler(timezone=os.getenv("TZ", "America/Guayaquil"))

    hora = int(os.getenv("LIMPIEZA_CRON_HORA", "3"))
    dia  = int(os.getenv("LIMPIEZA_CRON_DIA",  "6"))   # 6 = domingo (lun=0)

    _scheduler.add_job(
        _tarea_limpieza_lopdp,
        trigger=CronTrigger(day_of_week=dia, hour=hora, minute=0),
        id="limpieza_lopdp_semanal",
        name="Limpieza LOPDP semanal (borra entradas viejas)",
        replace_existing=True,
        misfire_grace_time=3600,  # tolera 1h de retraso si el server estaba caído
    )

    # Limpieza diaria de tokens de reset de password (housekeeping)
    _scheduler.add_job(
        _tarea_limpieza_tokens_reset,
        trigger=CronTrigger(hour=4, minute=15),   # diario 04:15
        id="limpieza_tokens_reset_diaria",
        name="Limpia tokens de reset password expirados / usados",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    _scheduler.start()
    print(f"[scheduler] ✅ iniciado — limpieza LOPDP cada semana día={dia} hora={hora}:00")
    print(f"[scheduler] ✅ iniciado — limpieza tokens reset diario hora=04:15")


def detener_scheduler() -> None:
    """Detiene el scheduler limpiamente (FastAPI shutdown event)."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        print("[scheduler] detenido")
