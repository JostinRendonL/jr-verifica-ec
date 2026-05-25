"""
Registro de códigos de verificación generados.

Cuando se genera un PDF, registramos su código + metadata.
El endpoint público /verificar/{codigo} muestra que el documento es auténtico.
"""
import os
import json
import threading
import time
from pathlib import Path
from typing import Optional

_DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_FILE = _DATA_DIR / "verificaciones.json"

_lock = threading.Lock()
_store: dict[str, dict] = {}


def _cargar():
    global _store
    if not _FILE.exists():
        _store = {}
        return
    try:
        with open(_FILE, "r", encoding="utf-8") as f:
            _store = json.load(f)
        print(f"[verificaciones] {len(_store)} códigos cargados")
    except Exception as e:
        print(f"[verificaciones] error cargando: {e}")
        _store = {}


def _guardar_disco():
    tmp = _FILE.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_store, f, ensure_ascii=False)
        tmp.replace(_FILE)
    except Exception as e:
        print(f"[verificaciones] error guardando: {e}")


_cargar()


def registrar(codigo: str, cedula: str, nombre: str, semaforo: str, timestamp: int) -> None:
    """Guarda un código generado para poder verificarlo después."""
    with _lock:
        _store[codigo] = {
            "cedula":    cedula,
            "nombre":    nombre or "",
            "semaforo":  semaforo or "",
            "timestamp": timestamp,
        }
        # Limitar a 10000 códigos
        if len(_store) > 10000:
            # Borrar los más viejos
            ordenados = sorted(_store.items(), key=lambda kv: kv[1]["timestamp"])
            for k, _ in ordenados[:len(_store) - 10000]:
                del _store[k]
        _guardar_disco()


def obtener(codigo: str) -> Optional[dict]:
    """Verifica si un código existe."""
    return _store.get(codigo)


def total() -> int:
    return len(_store)


def borrar_por_cedula(cedula: str) -> int:
    """LOPDP — borra todos los códigos de verificación de una cédula. Devuelve cuántos."""
    cedula = (cedula or "").strip()
    if not cedula:
        return 0
    with _lock:
        a_borrar = [k for k, v in _store.items() if v.get("cedula") == cedula]
        for k in a_borrar:
            del _store[k]
        if a_borrar:
            _guardar_disco()
    return len(a_borrar)


def borrar_antiguos(meses: int = 12) -> int:
    """LOPDP — borra códigos generados hace más de X meses. Devuelve cuántos."""
    if meses <= 0:
        return 0
    cutoff = int(time.time()) - (meses * 30 * 86400)
    with _lock:
        a_borrar = [k for k, v in _store.items() if v.get("timestamp", 0) < cutoff]
        for k in a_borrar:
            del _store[k]
        if a_borrar:
            _guardar_disco()
    return len(a_borrar)
