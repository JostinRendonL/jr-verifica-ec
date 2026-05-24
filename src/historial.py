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
from datetime import datetime
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


def borrar_entrada(id_entrada: str) -> bool:
    """Elimina una entrada específica del historial. Devuelve True si la borró."""
    global _entradas
    with _lock:
        antes = len(_entradas)
        _entradas = [e for e in _entradas if e.get("id") != id_entrada]
        cambio = len(_entradas) < antes
        if cambio:
            _guardar_disco()
        return cambio


def borrar_por_cedula(cedula: str) -> int:
    """Elimina TODAS las entradas para una cédula. Devuelve cuántas se borraron."""
    global _entradas
    cedula = (cedula or "").strip()
    if not cedula:
        return 0
    with _lock:
        antes = len(_entradas)
        _entradas = [e for e in _entradas if e.get("cedula") != cedula]
        borradas = antes - len(_entradas)
        if borradas:
            _guardar_disco()
        return borradas


def limpiar_todo() -> int:
    """Borra TODO el historial/caché. Devuelve cuántas entradas tenía."""
    global _entradas
    with _lock:
        n = len(_entradas)
        _entradas = []
        _guardar_disco()
        return n


# ── Stats para dashboard ─────────────────────────────────────────────────────

def calcular_stats() -> dict:
    """Calcula métricas agregadas para el dashboard."""
    ahora = int(time.time())
    UN_DIA  = 86400
    UNA_SEM = UN_DIA * 7
    UN_MES  = UN_DIA * 30

    total = len(_entradas)

    # Mapeo de etiquetas viejas (VERDE/AMARILLO/ROJO/GRIS) → nuevas
    MAPEO_VIEJO = {
        "VERDE":    "APTO",
        "AMARILLO": "OBSERVACIÓN",
        "ROJO":     "RECHAZAR",
        "GRIS":     "SIN DATOS",
    }

    # Conteos por nivel
    niveles = {"APTO": 0, "OBSERVACIÓN": 0, "RECHAZAR": 0, "CRÍTICO": 0, "SIN DATOS": 0, "OTROS": 0}
    delitos_count: dict[str, int] = {}
    instituciones: dict[str, int] = {}

    # Por día (últimos 30 días)
    por_dia: dict[str, int] = {}

    hoy_count   = 0
    semana_count = 0
    mes_count   = 0

    for e in _entradas:
        ts = e.get("timestamp", 0)
        sem_str = (e.get("semaforo", "") or "").upper()
        # Normalizar etiquetas viejas → nuevas
        for vieja, nueva in MAPEO_VIEJO.items():
            sem_str = sem_str.replace(vieja, nueva)

        # Si no tiene semaforo (consulta solo bachiller o solo satje), intentar calcularlo
        if not sem_str:
            resultado = e.get("resultado", {}) or {}
            b = resultado.get("bachiller", {}) or {}
            s = resultado.get("satje", {}) or {}
            if b and s:
                # Tiene ambos → podemos clasificar
                if s.get("total_demandado", 0) > 0:
                    sem_str = "RECHAZAR"
                elif b.get("estado") != "ENCONTRADO" or s.get("total_actor", 0) > 0:
                    sem_str = "OBSERVACIÓN"
                else:
                    sem_str = "APTO"

        # Nivel
        nivel = "OTROS"
        for k in niveles:
            if k in sem_str:
                nivel = k
                break
        niveles[nivel] = niveles.get(nivel, 0) + 1

        # Periodos
        if ahora - ts < UN_DIA:
            hoy_count += 1
        if ahora - ts < UNA_SEM:
            semana_count += 1
        if ahora - ts < UN_MES:
            mes_count += 1

        # Por día (último mes)
        if ahora - ts < UN_MES:
            dia_str = datetime.fromtimestamp(ts).strftime("%d/%m")
            por_dia[dia_str] = por_dia.get(dia_str, 0) + 1

        # Delitos detectados
        resultado = e.get("resultado", {}) or {}
        satje = resultado.get("satje", {}) or {}
        for d in (satje.get("delitos") or []):
            clave = d.upper().strip()[:60]
            if clave:
                delitos_count[clave] = delitos_count.get(clave, 0) + 1

        # Instituciones (de bachiller)
        bachiller = resultado.get("bachiller", {}) or {}
        inst = (bachiller.get("institucion") or "").strip()
        if inst:
            instituciones[inst] = instituciones.get(inst, 0) + 1

    # Top 10 delitos
    top_delitos = sorted(delitos_count.items(), key=lambda kv: kv[1], reverse=True)[:10]

    # Top 10 instituciones
    top_instituciones = sorted(instituciones.items(), key=lambda kv: kv[1], reverse=True)[:10]

    # Ordenar por_dia por fecha real (últimos 30 días, completar gaps con 0)
    series_dia = []
    for i in range(29, -1, -1):
        ts_dia = ahora - (i * UN_DIA)
        dia_str = datetime.fromtimestamp(ts_dia).strftime("%d/%m")
        series_dia.append({"dia": dia_str, "consultas": por_dia.get(dia_str, 0)})

    # Ahorro estimado: ~15 minutos de trabajo manual por consulta
    minutos_ahorrados = total * 15
    horas_ahorradas   = round(minutos_ahorrados / 60, 1)
    # Costo de un empleado: ~$5/hora (mínimo Ecuador)
    valor_ahorrado_usd = round(horas_ahorradas * 5, 2)

    return {
        "total":          total,
        "hoy":            hoy_count,
        "semana":         semana_count,
        "mes":            mes_count,
        "niveles":        niveles,
        "top_delitos":    top_delitos,
        "top_instituciones": top_instituciones,
        "series_dia":     series_dia,
        "horas_ahorradas": horas_ahorradas,
        "valor_ahorrado_usd": valor_ahorrado_usd,
    }
