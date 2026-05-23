"""Lectura y escritura de archivos Excel con look premium."""
from io import BytesIO
from datetime import datetime
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


# ── Paleta de colores premium ─────────────────────────────────────────────────
NAVY        = "1A3A5C"
NAVY_LIGHT  = "2980B9"
ACCENT      = "3498DB"

VERDE_BG    = "D4EFDF"
AMARILLO_BG = "FCF3CF"
ROJO_BG     = "F1948A"
GRIS_BG     = "EAEDED"

ROW_ALT_BG  = "FAFBFC"
HEADER_BG   = NAVY
BANNER_BG   = NAVY

TEXTO_OSCURO = "1C2833"
TEXTO_GRIS   = "7B7D7D"
BORDE_SUTIL  = "D5D8DC"

# ── Estilos reutilizables ─────────────────────────────────────────────────────
FONT_TITLE   = Font(name="Calibri", size=18, bold=True, color="FFFFFF")
FONT_SUB     = Font(name="Calibri", size=10, color="D5D8DC", italic=True)
FONT_HEADER  = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
FONT_STAT    = Font(name="Calibri", size=12, bold=True, color="FFFFFF")
FONT_BODY    = Font(name="Calibri", size=10, color=TEXTO_OSCURO)
FONT_BODY_B  = Font(name="Calibri", size=10, bold=True, color=TEXTO_OSCURO)
FONT_CEDULA  = Font(name="Consolas", size=10, color=TEXTO_OSCURO)

ALIGN_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
ALIGN_LEFT   = Alignment(horizontal="left", vertical="center", wrap_text=True, indent=1)

_BORDER = Border(
    left=Side(style="thin", color=BORDE_SUTIL),
    right=Side(style="thin", color=BORDE_SUTIL),
    top=Side(style="thin", color=BORDE_SUTIL),
    bottom=Side(style="thin", color=BORDE_SUTIL),
)


def leer_cedulas(file_bytes: bytes) -> tuple[list[dict], list[str]]:
    """
    Lee un Excel y devuelve (lista de dicts {cedula, nombre}, errores).
    Detecta columnas 'cedula' y opcionalmente 'nombre'.
    """
    try:
        wb = load_workbook(BytesIO(file_bytes), data_only=True)
        ws = wb.active

        # Buscar columnas en el header
        col_cedula = None
        col_nombre = None
        header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
        for i, val in enumerate(header_row):
            if not val:
                continue
            v = str(val).strip().lower()
            if col_cedula is None and v in ("cedula", "cédula", "ci", "identificacion", "identificación", "nº de identifi.", "n° de identifi."):
                col_cedula = i
            elif col_nombre is None and v in ("nombre", "nombres", "apellidos y nombres", "nombre completo", "nombre del titulado", "nombre del titulado"):
                col_nombre = i

        if col_cedula is None:
            col_cedula = 0
            data_start_row = 1
        else:
            data_start_row = 2

        items = []
        for row in ws.iter_rows(min_row=data_start_row, values_only=True):
            if col_cedula >= len(row):
                continue
            val = row[col_cedula]
            if val is None or str(val).strip() == "":
                continue
            cedula = str(val).strip()
            if cedula.isdigit() and len(cedula) < 10:
                cedula = cedula.zfill(10)

            nombre = ""
            if col_nombre is not None and col_nombre < len(row):
                n = row[col_nombre]
                if n:
                    nombre = str(n).strip()

            items.append({"cedula": cedula, "nombre": nombre})

        return items, []

    except Exception as e:
        return [], [f"Error leyendo Excel: {type(e).__name__}: {str(e)[:200]}"]


def _aplicar_borde(ws, rango_min_row, rango_max_row, rango_min_col, rango_max_col):
    for row in ws.iter_rows(min_row=rango_min_row, max_row=rango_max_row,
                            min_col=rango_min_col, max_col=rango_max_col):
        for cell in row:
            cell.border = _BORDER


def generar_excel_resultados(resultados: list[dict], tipo: str) -> bytes:
    """
    Genera un Excel premium con los resultados.
    Estructura: banner + stats + tabla.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Resultados"

    # ── Definir columnas según tipo ──────────────────────────────────────────
    if tipo == "bachiller":
        headers = ["Cédula", "Nombre", "Estado", "Título", "Especialidad", "Institución", "Año", "Detalle"]
        widths  = [14, 32, 16, 30, 24, 36, 10, 40]
    elif tipo == "satje":
        headers = ["Cédula", "Nombre", "Estado", "T. Demandado", "T. Actor", "Delitos / Detalle"]
        widths  = [14, 32, 18, 14, 14, 60]
    else:  # completo
        headers = [
            "Cédula", "Nombre", "🚦 Semáforo",
            "🎓 Bachiller", "Institución", "Año",
            "⚖️ Estado SATJE", "Demandado", "Actor", "Delitos / Detalle",
        ]
        widths  = [14, 30, 14, 26, 32, 10, 18, 12, 12, 50]

    num_cols = len(headers)

    # ── Fila 1: Banner con título y branding ─────────────────────────────────
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=num_cols)
    cell = ws.cell(row=1, column=1, value="⚙️ JR Verifica EC")
    cell.fill      = PatternFill(start_color=BANNER_BG, end_color=BANNER_BG, fill_type="solid")
    cell.font      = FONT_TITLE
    cell.alignment = Alignment(horizontal="left", vertical="center", indent=2)
    ws.row_dimensions[1].height = 42

    # ── Fila 2: Subtitle con fecha + tipo de búsqueda ────────────────────────
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=num_cols)
    tipo_label = {"bachiller": "Bachiller (Min. Educación)",
                  "satje":     "Procesos Judiciales (SATJE)",
                  "completo":  "Verificación completa (Bachiller + SATJE)"}[tipo]
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    sub = ws.cell(row=2, column=1, value=f"{tipo_label}  ·  Generado: {fecha}  ·  Powered by JR Automata")
    sub.fill      = PatternFill(start_color=BANNER_BG, end_color=BANNER_BG, fill_type="solid")
    sub.font      = FONT_SUB
    sub.alignment = Alignment(horizontal="left", vertical="center", indent=2)
    ws.row_dimensions[2].height = 22

    # ── Fila 3: Stats (solo en modo completo) ────────────────────────────────
    if tipo == "completo":
        verdes    = sum(1 for r in resultados if "VERDE"    in r.get("semaforo", ""))
        amarillos = sum(1 for r in resultados if "AMARILLO" in r.get("semaforo", ""))
        rojos     = sum(1 for r in resultados if "ROJO"     in r.get("semaforo", ""))
        gris      = sum(1 for r in resultados if "GRIS"     in r.get("semaforo", ""))

        stats_text = (
            f"📊 TOTAL: {len(resultados)}     "
            f"🟢 VERDES: {verdes}     "
            f"🟡 AMARILLOS: {amarillos}     "
            f"🔴 ROJOS: {rojos}     "
            f"⚪ GRIS: {gris}"
        )
        ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=num_cols)
        st = ws.cell(row=3, column=1, value=stats_text)
        st.fill      = PatternFill(start_color=NAVY_LIGHT, end_color=NAVY_LIGHT, fill_type="solid")
        st.font      = FONT_STAT
        st.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[3].height = 32
        header_row_num = 4
    else:
        # Banner adicional con conteo simple
        ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=num_cols)
        st = ws.cell(row=3, column=1, value=f"📊 TOTAL CONSULTADOS: {len(resultados)}")
        st.fill      = PatternFill(start_color=NAVY_LIGHT, end_color=NAVY_LIGHT, fill_type="solid")
        st.font      = FONT_STAT
        st.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[3].height = 32
        header_row_num = 4

    # ── Headers ──────────────────────────────────────────────────────────────
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=header_row_num, column=i, value=h)
        c.fill      = PatternFill(start_color=HEADER_BG, end_color=HEADER_BG, fill_type="solid")
        c.font      = FONT_HEADER
        c.alignment = ALIGN_CENTER
        c.border    = _BORDER
    ws.row_dimensions[header_row_num].height = 38

    # ── Anchos de columna ────────────────────────────────────────────────────
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # ── Filas de datos ───────────────────────────────────────────────────────
    for idx, r in enumerate(resultados, start=header_row_num + 1):
        b = r.get("bachiller", {})
        s = r.get("satje", {})
        nombre = r.get("nombre", "") or b.get("nombre", "") or ""

        if tipo == "bachiller":
            fila = [
                r.get("cedula", ""), nombre,
                b.get("estado", ""),
                b.get("titulo", ""),
                b.get("especialidad", ""),
                b.get("institucion", ""),
                (b.get("fecha_grado") or "")[:4],
                b.get("detalle", ""),
            ]
        elif tipo == "satje":
            fila = [
                r.get("cedula", ""), nombre,
                s.get("estado", ""),
                s.get("total_demandado", ""),
                s.get("total_actor", ""),
                s.get("detalle", ""),
            ]
        else:
            sem = r.get("semaforo", "")
            fila = [
                r.get("cedula", ""), nombre, sem,
                f"{b.get('titulo', '')} ({b.get('especialidad', '')})".strip(" ()") if b.get('titulo') else b.get("estado", ""),
                b.get("institucion", ""),
                (b.get("fecha_grado") or "")[:4],
                s.get("estado", ""),
                s.get("total_demandado", ""),
                s.get("total_actor", ""),
                s.get("detalle", ""),
            ]

        # Banda alternada
        es_par = (idx - header_row_num) % 2 == 0
        bg_color = ROW_ALT_BG if es_par else "FFFFFF"

        for i, val in enumerate(fila, start=1):
            c = ws.cell(row=idx, column=i, value=val)
            c.fill      = PatternFill(start_color=bg_color, end_color=bg_color, fill_type="solid")
            c.font      = FONT_CEDULA if i == 1 else FONT_BODY
            c.alignment = ALIGN_LEFT if i in (2, 4, 5, 6, 10) else ALIGN_CENTER
            c.border    = _BORDER

        # Color del semáforo
        if tipo == "completo":
            sem = r.get("semaforo", "")
            sem_cell = ws.cell(row=idx, column=3)
            if "VERDE" in sem:
                sem_cell.fill = PatternFill(start_color=VERDE_BG,    end_color=VERDE_BG,    fill_type="solid")
            elif "AMARILLO" in sem:
                sem_cell.fill = PatternFill(start_color=AMARILLO_BG, end_color=AMARILLO_BG, fill_type="solid")
            elif "ROJO" in sem:
                sem_cell.fill = PatternFill(start_color=ROJO_BG,     end_color=ROJO_BG,     fill_type="solid")
            elif "GRIS" in sem:
                sem_cell.fill = PatternFill(start_color=GRIS_BG,     end_color=GRIS_BG,     fill_type="solid")
            sem_cell.font = FONT_BODY_B
            sem_cell.alignment = ALIGN_CENTER

        # Resaltar SATJE con procesos en rojo
        if tipo in ("satje", "completo"):
            col_estado_satje = 3 if tipo == "satje" else 7
            estado_cell = ws.cell(row=idx, column=col_estado_satje)
            if "TIENE_PROCESOS" in str(estado_cell.value):
                estado_cell.fill = PatternFill(start_color=ROJO_BG, end_color=ROJO_BG, fill_type="solid")
                estado_cell.font = FONT_BODY_B

        ws.row_dimensions[idx].height = 32

    # Congelar filas de header + branding
    ws.freeze_panes = ws.cell(row=header_row_num + 1, column=3)  # también freezea cédula+nombre

    # Auto-filter en la tabla
    last_col_letter = get_column_letter(num_cols)
    ws.auto_filter.ref = f"A{header_row_num}:{last_col_letter}{header_row_num + len(resultados)}"

    # Guardar
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def generar_excel_plantilla() -> bytes:
    """Plantilla con look premium para que el usuario llene cédulas + nombres opcionales."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Cédulas"

    # Banner
    ws.merge_cells("A1:B1")
    c = ws.cell(row=1, column=1, value="⚙️ JR Verifica EC — Plantilla")
    c.fill      = PatternFill(start_color=BANNER_BG, end_color=BANNER_BG, fill_type="solid")
    c.font      = FONT_TITLE
    c.alignment = Alignment(horizontal="left", vertical="center", indent=2)
    ws.row_dimensions[1].height = 42

    # Instrucciones
    ws.merge_cells("A2:B2")
    s = ws.cell(row=2, column=1, value="Pega tus cédulas en columna A. El nombre es opcional.")
    s.fill      = PatternFill(start_color=BANNER_BG, end_color=BANNER_BG, fill_type="solid")
    s.font      = FONT_SUB
    s.alignment = Alignment(horizontal="left", vertical="center", indent=2)
    ws.row_dimensions[2].height = 22

    # Headers
    headers = ["cedula", "nombre"]
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=3, column=i, value=h)
        c.fill      = PatternFill(start_color=HEADER_BG, end_color=HEADER_BG, fill_type="solid")
        c.font      = FONT_HEADER
        c.alignment = ALIGN_CENTER
        c.border    = _BORDER
    ws.row_dimensions[3].height = 32

    # Ejemplos
    ejemplos = [
        ("0954008272", "Jostin Rendón (ejemplo)"),
        ("1309022935", "Fito (ejemplo)"),
    ]
    for i, (ced, nom) in enumerate(ejemplos, start=4):
        ws.cell(row=i, column=1, value=ced).font = FONT_CEDULA
        ws.cell(row=i, column=2, value=nom).font = FONT_BODY
        for col in (1, 2):
            cc = ws.cell(row=i, column=col)
            cc.border    = _BORDER
            cc.alignment = ALIGN_LEFT

    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 40
    ws.freeze_panes = "A4"

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()
