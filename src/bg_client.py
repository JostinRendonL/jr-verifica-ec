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
        "setec":     "/consultar/setec",
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

    # Extraer nombre desde las causas — primero demandado (sujeto consultado),
    # luego actor. Útil como fallback cuando Bachiller no encuentra al candidato.
    nombre = ""
    for c in (s.get("causas_demandado") or []):
        n = (c.get("nombreDemandado") or "").strip()
        if n and len(n) > 3:
            nombre = n
            break
    if not nombre:
        for c in (s.get("causas_actor") or []):
            n = (c.get("nombreActor") or "").strip()
            if n and len(n) > 3:
                nombre = n
                break

    if td == 0 and ta == 0:
        return {"estado": "SIN_PROCESOS", "total_demandado": 0, "total_actor": 0, "delitos": [], "nombre": nombre}

    return {
        "estado":          "TIENE_PROCESOS",
        "total_demandado": td,
        "total_actor":     ta,
        "delitos":         delitos,
        "nombre":          nombre,
        "detalle":         "; ".join(delitos) if delitos else f"{td} demandado, {ta} actor",
    }


def extraer_setec(data: dict) -> dict | None:
    """
    Extrae datos de SETEC de la respuesta del bg-api.
    Maneja dos formatos:
      - Respuesta plana de /consultar/setec: la data ES el payload de SETEC
      - Respuesta anidada de /completo (legacy): data["setec"] contiene el payload
    """
    if not data.get("ok"):
        return {"estado": "ERROR", "detalle": data.get("error", "sin datos"), "cursos": [], "total": 0}

    # Si viene de /consultar/setec: la data es plana (tiene_certificados en el top level)
    # Si viene de /completo (legacy): está anidada en data["setec"]
    raw = data.get("setec") or data

    if raw.get("error"):
        return {"estado": "ERROR", "detalle": raw["error"], "cursos": [], "total": 0}
    if raw.get("tiene_certificados"):
        cursos = [c.strip() for c in (raw.get("detalle_cursos") or "").split("|") if c.strip()]
        return {
            "estado":  "TIENE_CERTIFICADOS",
            "cursos":  cursos,
            "total":   raw.get("total_cursos", len(cursos)),
            "detalle": raw.get("detalle_cursos", ""),
        }
    return {"estado": "SIN_CERTIFICADOS", "cursos": [], "total": 0, "detalle": "Sin registros"}
