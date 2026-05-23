"""Cliente HTTP del bg-api (Background Checks Ecuador)."""
import os
import httpx
from typing import Literal

BG_API_URL     = os.getenv("BG_API_URL", "http://dentaklin_bg-api:8000")
BG_API_KEY     = os.getenv("BG_API_KEY", "")
BG_API_TIMEOUT = float(os.getenv("BG_API_TIMEOUT", "120"))


def _cedula_valida(cedula: str) -> bool:
    c = (cedula or "").strip()
    return c.isdigit() and len(c) == 10


async def consultar(
    cedula: str,
    tipo: Literal["bachiller", "satje", "completo"] = "completo",
) -> dict:
    """
    Llama al bg-api y devuelve el resultado.
    tipo: 'bachiller', 'satje', o 'completo' (ambos).
    """
    cedula = (cedula or "").strip()
    if not _cedula_valida(cedula):
        return {
            "cedula":   cedula,
            "ok":       False,
            "error":    "Cédula inválida (debe tener 10 dígitos)",
            "tipo":     tipo,
        }

    endpoint = {
        "bachiller": "/consultar/bachiller",
        "satje":     "/consultar/satje",
        "completo":  "/consultar/completo",
    }[tipo]

    try:
        async with httpx.AsyncClient(timeout=BG_API_TIMEOUT) as client:
            r = await client.post(
                f"{BG_API_URL}{endpoint}",
                headers={
                    "X-API-Key":    BG_API_KEY,
                    "Content-Type": "application/json",
                },
                json={"cedula": cedula},
            )
            r.raise_for_status()
            data = r.json()
            data["cedula"] = cedula
            data["ok"]     = True
            data["tipo"]   = tipo
            return data
    except httpx.TimeoutException:
        return {
            "cedula": cedula, "ok": False,
            "error": "Timeout — el servidor tardó demasiado", "tipo": tipo,
        }
    except httpx.HTTPStatusError as e:
        return {
            "cedula": cedula, "ok": False,
            "error": f"HTTP {e.response.status_code}: {e.response.text[:100]}",
            "tipo": tipo,
        }
    except Exception as e:
        return {
            "cedula": cedula, "ok": False,
            "error": f"{type(e).__name__}: {str(e)[:120]}",
            "tipo": tipo,
        }


# ── Helpers de extracción ────────────────────────────────────────────────────

def extraer_bachiller(data: dict) -> dict:
    """De la respuesta del bg-api, extrae los campos clave del Bachiller."""
    if not data.get("ok"):
        return {"estado": "ERROR", "detalle": data.get("error", "sin datos")}

    # Si vino del endpoint /completo, los datos están en .bachiller
    b = data.get("bachiller", data)

    estado = b.get("estado", "DESCONOCIDO")
    if estado == "ENCONTRADO" or b.get("tiene_titulo"):
        return {
            "estado":       "ENCONTRADO",
            "nombre":       b.get("nombre", ""),
            "titulo":       b.get("titulo", ""),
            "especialidad": b.get("especialidad", ""),
            "institucion":  b.get("institucion", ""),
            "fecha_grado":  b.get("fecha_grado", ""),
            "detalle":      "",
        }
    if estado == "NO_ENCONTRADO":
        return {
            "estado":  "NO_ENCONTRADO",
            "detalle": "No existe registro de título de bachiller",
        }
    return {
        "estado":  estado,
        "detalle": b.get("detalle", ""),
    }


def extraer_satje(data: dict) -> dict:
    """De la respuesta del bg-api, extrae los campos clave de SATJE."""
    if not data.get("ok"):
        return {"estado": "ERROR", "detalle": data.get("error", "sin datos")}

    s = data.get("satje", data)

    if s.get("status") == "ERROR":
        return {"estado": "ERROR", "detalle": s.get("detalle", "")}

    td = s.get("total_demandado", 0)
    ta = s.get("total_actor", 0)

    delitos = []
    for c in (s.get("causas_demandado") or [])[:10]:
        d = (c.get("delito") or "").strip()
        if d:
            # Acortar "144 HOMICIDIO" → "HOMICIDIO"
            partes = d.split()
            d_corto = " ".join(partes[1:]) if partes and partes[0].isdigit() else d
            delitos.append(d_corto[:80])

    if td == 0 and ta == 0:
        return {"estado": "SIN_PROCESOS", "total_demandado": 0, "total_actor": 0, "delitos": []}

    return {
        "estado":          "TIENE_PROCESOS",
        "total_demandado": td,
        "total_actor":     ta,
        "delitos":         delitos,
        "detalle":         "; ".join(delitos) if delitos else f"{td} demandado, {ta} actor",
    }
