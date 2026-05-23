"""Lectura y escritura de archivos Excel."""
from io import BytesIO
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side


# ── Estilos visuales ──────────────────────────────────────────────────────────
_HEADER_FILL  = PatternFill(start_color="1A3A5C", end_color="1A3A5C", fill_type="solid")
_HEADER_FONT  = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
_HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)

_BORDER_THIN  = Border(
    left=Side(style="thin", color="D5D8DC"),
    right=Side(style="thin", color="D5D8DC"),
    top=Side(style="thin", color="D5D8DC"),
    bottom=Side(style="thin", color="D5D8DC"),
)

_VERDE_FILL    = PatternFill(start_color="D4EFDF", end_color="D4EFDF", fill_type="solid")
_AMARILLO_FILL = PatternFill(start_color="FCF3CF", end_color="FCF3CF", fill_type="solid")
_ROJO_FILL     = PatternFill(start_color="F1948A", end_color="F1948A", fill_type="solid")


def leer_cedulas(file_bytes: bytes) -> tuple[list[str], list[str]]:
    """
    Lee un Excel y devuelve (cédulas, errores).
    Busca la columna 'cedula' o 'cédula' (case-insensitive). Si no la encuentra,
    usa la primera columna.
    """
    try:
        wb = load_workbook(BytesIO(file_bytes), data_only=True)
        ws = wb.active

        # Buscar columna de cédulas
        col_cedula = None
        header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
        for i, val in enumerate(header_row):
            if val and str(val).strip().lower() in ("cedula", "cédula", "ci", "identificacion", "identificación"):
                col_cedula = i
                break

        # Si no hay header reconocido, asumir col A
        if col_cedula is None:
            col_cedula = 0
            data_start_row = 1  # leer desde fila 1 (no hay header)
        else:
            data_start_row = 2  # saltar header

        cedulas = []
        errores = []
        for row_idx, row in enumerate(ws.iter_rows(min_row=data_start_row, values_only=True), start=data_start_row):
            if col_cedula >= len(row):
                continue
            val = row[col_cedula]
            if val is None or str(val).strip() == "":
                continue
            cedula = str(val).strip()
            # Normalizar: si vino como número, padding con 0 a 10 dígitos
            if cedula.isdigit() and len(cedula) < 10:
                cedula = cedula.zfill(10)
            cedulas.append(cedula)

        return cedulas, errores

    except Exception as e:
        return [], [f"Error leyendo Excel: {type(e).__name__}: {str(e)[:200]}"]


def generar_excel_resultados(resultados: list[dict], tipo: str) -> bytes:
    """
    Genera un Excel descargable con los resultados.
    tipo: 'bachiller', 'satje', o 'completo'.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Resultados"

    # ── Construir headers según el tipo ──────────────────────────────────────
    if tipo == "bachiller":
        headers = ["Cédula", "Estado", "Nombre", "Título", "Especialidad", "Institución", "Fecha Grado", "Detalle"]
    elif tipo == "satje":
        headers = ["Cédula", "Estado", "Total Demandado", "Total Actor", "Delitos / Detalle"]
    else:  # completo
        headers = [
            "Cédula", "Semáforo",
            "Bachiller Estado", "Bachiller Nombre", "Bachiller Título", "Bachiller Institución", "Bachiller Año",
            "SATJE Estado", "Total Demandado", "Total Actor", "Delitos / Detalle",
        ]

    # Escribir headers con estilo
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=i, value=h)
        c.fill      = _HEADER_FILL
        c.font      = _HEADER_FONT
        c.alignment = _HEADER_ALIGN
        c.border    = _BORDER_THIN

    ws.row_dimensions[1].height = 38

    # Anchos de columna sugeridos
    if tipo == "bachiller":
        widths = [14, 18, 28, 28, 22, 30, 14, 50]
    elif tipo == "satje":
        widths = [14, 22, 16, 14, 70]
    else:
        widths = [14, 16, 20, 28, 26, 30, 12, 22, 16, 14, 60]

    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w

    # ── Escribir filas ────────────────────────────────────────────────────────
    for row_idx, r in enumerate(resultados, start=2):
        if tipo == "bachiller":
            b = r.get("bachiller", {})
            fila = [
                r.get("cedula", ""),
                b.get("estado", ""),
                b.get("nombre", ""),
                b.get("titulo", ""),
                b.get("especialidad", ""),
                b.get("institucion", ""),
                b.get("fecha_grado", ""),
                b.get("detalle", ""),
            ]
        elif tipo == "satje":
            s = r.get("satje", {})
            fila = [
                r.get("cedula", ""),
                s.get("estado", ""),
                s.get("total_demandado", ""),
                s.get("total_actor", ""),
                s.get("detalle", ""),
            ]
        else:  # completo
            b = r.get("bachiller", {})
            s = r.get("satje", {})
            sem = r.get("semaforo", "")
            fila = [
                r.get("cedula", ""),
                sem,
                b.get("estado", ""),
                b.get("nombre", ""),
                b.get("titulo", ""),
                b.get("institucion", ""),
                (b.get("fecha_grado") or "")[:4],
                s.get("estado", ""),
                s.get("total_demandado", ""),
                s.get("total_actor", ""),
                s.get("detalle", ""),
            ]

        for i, val in enumerate(fila, start=1):
            c = ws.cell(row=row_idx, column=i, value=val)
            c.border    = _BORDER_THIN
            c.alignment = Alignment(vertical="center", wrap_text=True)

        # Color del semáforo (solo en modo completo)
        if tipo == "completo":
            sem = r.get("semaforo", "")
            cell = ws.cell(row=row_idx, column=2)
            if "VERDE" in sem:
                cell.fill = _VERDE_FILL
            elif "AMARILLO" in sem:
                cell.fill = _AMARILLO_FILL
            elif "ROJO" in sem:
                cell.fill = _ROJO_FILL
            cell.font = Font(bold=True)

        ws.row_dimensions[row_idx].height = 50

    # Congelar header
    ws.freeze_panes = "A2"

    # Guardar a bytes
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def generar_excel_plantilla() -> bytes:
    """Genera una plantilla Excel vacía para que el usuario llene cédulas."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Cédulas"

    c = ws.cell(row=1, column=1, value="cedula")
    c.fill      = _HEADER_FILL
    c.font      = _HEADER_FONT
    c.alignment = _HEADER_ALIGN
    c.border    = _BORDER_THIN

    # Ejemplos
    ws.cell(row=2, column=1, value="0954008272")
    ws.cell(row=3, column=1, value="1309022935")

    ws.column_dimensions["A"].width = 18
    ws.row_dimensions[1].height = 35

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()
