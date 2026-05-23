"""
Historial + Caché persistente en disco.

- Cada consulta queda guardada en historial.json
- Si la misma cédula se consulta de nuevo en < 24h, devuelve el resultado cacheado
- Sin DB, sin Redis — un solo archivo JSON cargado en memoria
"""
import os
import json
import time
import threading
from pathlib import Path
from typing import Optional

# TTL del caché en segundos
CACHE_TTL_SEG = int(os.getenv("CACHE_TTL_SEG", str(60 * 60 * 24)))  # 24h por default

# Path del archivo (en /app/data/ para que el volumen de Docker lo persista)
_DATA_DIR  = Path(os.getenv("DATA_DIR", "/app/data"))
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_HIST_FILE = _DATA_DIR / "historial.json"

# Lock para escritura concurrente
_lock = threading.Lock()

# In-memory store: lista de entradas
# Cada entrada: {
#   "id":         "abc123",
#   "cedula":     "0954008272",
#   "tipo":       "completo" | "bachiller" | "satje",
#   "timestamp":  1716489600,
#   "semaforo":   "🟢 VERDE" | etc,
#   "nombre":     "RENDON LOZANO JOSTIN ALEJANDRO",
#   "resultado":  {...},   # estructura completa
# }
_entradas: list[dict] = []


# ── Init: cargar desde disco ─────────────────────────────────────────────────

def _cargar() -> None:
    global _entradas
    if not _HIST_FILE.exists():
        _entradas = []
        return
    try:
        with open(_HIST_FILE, "r", encoding="utf-8") as f:
            _entradas = json.load(f)
        print(f"[historial] Cargadas {len(_entradas)} entradas desde {_HIST_FILE}")
    except Exception as e:
        print(f"[historial] Error cargando: {e} — empezando vacío")
        _entradas = []


def _guardar_disco() -> None:
    """Escribe el historial a disco (atómico via archivo temporal)."""
    tmp = _HIST_FILE.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_entradas, f, ensure_ascii=False, indent=None)
        tmp.replace(_HIST_FILE)
    except Exception as e:
        print(f"[historial] Error guardando a disco: {e}")


_cargar()


# ── API pública ──────────────────────────────────────────────────────────────

def buscar_cache(cedula: str, tipo: str) -> Optional[dict]:
    """
    Si existe una entrada para esta cédula+tipo dentro del TTL, retornar el resultado.
    Si tipo='completo' busca también si hay una entrada 'completo' válida.
    """
    cedula = (cedula or "").strip()
    if not cedula:
        return None

    ahora = time.time()
    # Iterar de las más recientes a las más viejas
    for e in reversed(_entradas):
        if e["cedula"] != cedula:
            continue
        if ahora - e["timestamp"] > CACHE_TTL_SEG:
            return None  # ya están todas más viejas
        # Match: si pedimos lo mismo o si hay un "completo" sirve para sub-tipos
        if e["tipo"] == tipo:
            return e["resultado"]
        if tipo in ("bachiller", "satje") and e["tipo"] == "completo":
            return e["resultado"]
    return None


def registrar(resultado: dict, tipo: str) -> None:
    """
    Agrega una entrada al historial y la persiste a disco.
    `resultado` debe tener al menos: cedula, semaforo (opcional), nombre (opcional).
    """
    entrada = {
        "id":        f"{int(time.time() * 1000):x}",
        "cedula":    resultado.get("cedula", ""),
        "tipo":      tipo,
        "timestamp": int(time.time()),
        "semaforo":  resultado.get("semaforo", ""),
        "nombre":    resultado.get("nombre") or (resultado.get("bachiller") or {}).get("nombre", ""),
        "resultado": resultado,
    }
    with _lock:
        _entradas.append(entrada)
        # Limitar a las últimas 5000 entradas para no crecer infinitamente
        if len(_entradas) > 5000:
            del _entradas[:len(_entradas) - 5000]
        _guardar_disco()


def listar(filtro_cedula: str = "", filtro_semaforo: str = "", limite: int = 200) -> list[dict]:
    """
    Devuelve las entradas más recientes filtradas (sin el campo `resultado` completo).
    """
    cedula_f   = (filtro_cedula or "").strip()
    semaforo_f = (filtro_semaforo or "").strip().upper()

    salida = []
    for e in reversed(_entradas):
        if cedula_f and cedula_f not in e["cedula"]:
            continue
        if semaforo_f and semaforo_f not in e["semaforo"].upper():
            continue
        salida.append({
            "id":        e["id"],
            "cedula":    e["cedula"],
            "tipo":      e["tipo"],
            "timestamp": e["timestamp"],
            "semaforo":  e["semaforo"],
            "nombre":    e["nombre"],
            "edad_seg":  int(time.time()) - e["timestamp"],
        })
        if len(salida) >= limite:
            break
    return salida


def obtener_resultado(id_entrada: str) -> Optional[dict]:
    """Trae el resultado completo de una entrada por ID."""
    for e in _entradas:
        if e["id"] == id_entrada:
            return {**e, "edad_seg": int(time.time()) - e["timestamp"]}
    return None


def total_entradas() -> int:
    return len(_entradas)
