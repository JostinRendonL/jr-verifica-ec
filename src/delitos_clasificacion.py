"""
delitos_clasificacion.py — Clasificación de delitos en 3 niveles para semáforo.

Reemplaza la lógica binaria anterior (CRÍTICO vs todo) por una matizada:
- CRÍTICO    → rechazo absoluto, alerta inmediata
- RECHAZAR   → descalifica laboralmente
- OBSERVACION → personal/civil, solo revisar
- SIN_DELITOS → no aplica

Convención: comparación por substring case-insensitive contra el delito
recibido. Se limpia prefijo numérico tipo "144 HOMICIDIO" → "HOMICIDIO".
"""

# ── 🚨 CRÍTICO — rechazo absoluto + alerta inmediata ────────────────────────
DELITOS_CRITICO = {
    # Contra la vida
    "ASESINATO", "HOMICIDIO", "FEMICIDIO", "PARRICIDIO", "SICARIATO",
    "TENTATIVA DE HOMICIDIO",
    # Sexual
    "VIOLACION", "VIOLACIÓN", "ABUSO SEXUAL", "ESTUPRO",
    "ACOSO SEXUAL", "PORNOGRAFIA INFANTIL", "PORNOGRAFÍA INFANTIL",
    # Libertad
    "SECUESTRO", "PLAGIO", "TRATA DE PERSONAS",
    # Drogas/Crimen organizado
    "NARCOTRAFICO", "NARCOTRÁFICO", "DROGAS", "ESTUPEFACIENTES",
    "DELINCUENCIA ORGANIZADA",
    # Estado/Terrorismo
    "TERRORISMO", "REBELION", "REBELIÓN",
    # Corrupción/Lavado
    "PECULADO", "ENRIQUECIMIENTO ILICITO", "ENRIQUECIMIENTO ILÍCITO",
    "LAVADO DE ACTIVOS",
    # Armas pesadas
    "TENENCIA DE ARMAS DE GUERRA",
}

# ── 🔴 RECHAZAR — descalifica laboralmente ──────────────────────────────────
DELITOS_RECHAZAR = {
    # Patrimonio con violencia o engaño
    "ROBO", "ASALTO", "EXTORSION", "EXTORSIÓN",
    "HURTO", "RECEPTACION", "RECEPTACIÓN",
    "APROPIACION INDEBIDA", "APROPIACIÓN INDEBIDA",
    # Fraude
    "ESTAFA", "FALSIFICACION", "FALSIFICACIÓN", "USURA",
    "FRAUDE", "DEFRAUDACION", "DEFRAUDACIÓN",
    # Lesiones / Agresión
    "LESIONES", "AGRESION", "AGRESIÓN",
    "VIOLENCIA INTRAFAMILIAR",
    # Amenazas
    "AMENAZAS", "INTIMIDACION", "INTIMIDACIÓN", "COACCION", "COACCIÓN",
    # Tránsito grave
    "CONDUCCION EN ESTADO DE EMBRIAGUEZ", "CONDUCCIÓN EN ESTADO DE EMBRIAGUEZ",
    "ACCIDENTE DE TRANSITO CON LESIONES", "ACCIDENTE DE TRÁNSITO CON LESIONES",
    # Corrupción menor
    "COHECHO", "CONCUSION", "CONCUSIÓN",
    # Tenencia ilegal armas (no de guerra)
    "TENENCIA ILEGAL DE ARMAS",
    # Daños
    "DANOS", "DAÑOS", "INCENDIO",
}

# ── 🟡 OBSERVACIÓN — personal/civil, no descalifica ─────────────────────────
DELITOS_OBSERVACION = {
    # Familia
    "ALIMENTOS", "PENSION ALIMENTICIA", "PENSIÓN ALIMENTICIA",
    "FIJACION DE PENSION", "FIJACIÓN DE PENSIÓN",
    "DIVORCIO", "PATERNIDAD", "TENENCIA",
    "LIQUIDACION DE SOCIEDAD CONYUGAL", "LIQUIDACIÓN DE SOCIEDAD CONYUGAL",
    # Civil/Patrimonio leve
    "COBRO DE DINERO", "CONTRATO", "LABORAL",
    # Tránsito menor
    "ACCIDENTE DE TRANSITO SOLO DANOS", "ACCIDENTE DE TRÁNSITO SOLO DAÑOS",
    "MULTAS", "CONTRAVENCION", "CONTRAVENCIÓN",
    # Lesiones leves
    "LESIONES LEVES",
}


def _normalizar(delito: str) -> str:
    """Normaliza un delito para comparación: upper + strip + sin prefijo numérico."""
    if not delito:
        return ""
    d = str(delito).upper().strip()
    # Limpiar prefijo numérico tipo "144 HOMICIDIO" -> "HOMICIDIO"
    parts = d.split()
    if parts and parts[0].isdigit():
        d = " ".join(parts[1:])
    return d


def clasificar_delito(delito: str) -> str:
    """
    Clasifica un delito en uno de los 4 niveles.
    Devuelve: "CRITICO" | "RECHAZAR" | "OBSERVACION" | "DESCONOCIDO"

    Orden de match: CRÍTICO > RECHAZAR > OBSERVACIÓN > DESCONOCIDO
    """
    if not delito:
        return "DESCONOCIDO"
    d = _normalizar(delito)
    if not d:
        return "DESCONOCIDO"

    # IMPORTANTE: chequear OBSERVACIÓN ANTES que RECHAZAR para que ALIMENTOS
    # (en OBS) gane sobre potenciales matches parciales. Pero CRÍTICO primero.
    for crit in DELITOS_CRITICO:
        if crit in d:
            return "CRITICO"
    # Excepción: si el delito tiene "LESIONES LEVES" no debe matchear "LESIONES"
    # Por eso OBSERVACION antes que RECHAZAR para los compuestos con LEVES
    for obs in DELITOS_OBSERVACION:
        if obs in d:
            return "OBSERVACION"
    for rech in DELITOS_RECHAZAR:
        if rech in d:
            return "RECHAZAR"
    return "DESCONOCIDO"


def clasificar_lista_delitos(delitos: list) -> str:
    """
    Para una lista de delitos, devuelve el PEOR nivel encontrado.
    Devuelve: "CRITICO" | "RECHAZAR" | "OBSERVACION" | "SIN_DELITOS"

    DESCONOCIDO se trata como RECHAZAR (conservador para HR).
    """
    if not delitos:
        return "SIN_DELITOS"
    niveles = [clasificar_delito(d) for d in delitos if d]
    if not niveles:
        return "SIN_DELITOS"
    if "CRITICO" in niveles:
        return "CRITICO"
    if "RECHAZAR" in niveles or "DESCONOCIDO" in niveles:
        return "RECHAZAR"
    return "OBSERVACION"


def resumir_delitos(causas: list, max_items: int = 5) -> str:
    """
    Convierte lista de causas en string compacto agrupado por delito.
    Ej: "ALIMENTOS (3) | DESPIDO (1) | DIVORCIO (1)"

    Args:
        causas: lista de dicts con campo "delito"
        max_items: top N delitos a mostrar (resto se suma como "+N más")
    """
    from collections import Counter
    if not causas:
        return ""
    counts = Counter()
    for c in causas:
        d = (c.get("delito") if isinstance(c, dict) else str(c)) or ""
        d = _normalizar(d)
        if d:
            counts[d[:40]] += 1
    if not counts:
        return ""
    top = counts.most_common(max_items)
    extra = f" (+{len(counts) - max_items} más)" if len(counts) > max_items else ""
    return " | ".join(f"{d} ({n})" if n > 1 else d for d, n in top) + extra
