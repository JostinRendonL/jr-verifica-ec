"""
Generador de PDF profesional para JR Verifica EC.

Convierte un resultado de verificación en un documento PDF descargable
con branding, sellos de autenticidad y código QR de verificación.
"""
import os
import io
import base64
import hashlib
import time
from datetime import datetime
from pathlib import Path

from weasyprint import HTML, CSS
import qrcode

from src.verificaciones import registrar as registrar_verificacion

# Timezone Ecuador (UTC-5) — sin DST
try:
    from zoneinfo import ZoneInfo
    _TZ_EC = ZoneInfo("America/Guayaquil")
except ImportError:
    # Fallback para Python < 3.9
    from datetime import timezone, timedelta
    _TZ_EC = timezone(timedelta(hours=-5))


def _ahora_ec() -> datetime:
    """Devuelve datetime actual en zona horaria de Ecuador."""
    return datetime.now(_TZ_EC)

# Secret para firmar los hashes de verificación
_SECRET     = os.getenv("PDF_VERIFY_SECRET", os.getenv("SESSION_SECRET", "jr-default"))
_PUBLIC_URL = os.getenv("PUBLIC_URL", "https://verifica.dentaklin.shop")


def _hash_verificacion(cedula: str, timestamp: int) -> str:
    """Genera un código corto de verificación único."""
    base = f"{cedula}|{timestamp}|{_SECRET}"
    h = hashlib.sha256(base.encode()).hexdigest()
    return h[:16].upper()  # 16 chars


def _qr_base64(texto: str) -> str:
    """Genera un QR como imagen base64 inline."""
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=4, border=1)
    qr.add_data(texto)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0F2C5C", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _img_b64(rel_path: str) -> str:
    """Carga una imagen de static/ y devuelve base64. Retorna '' si no existe."""
    p = Path(__file__).parent / "static" / rel_path
    if not p.exists():
        return ""
    return base64.b64encode(p.read_bytes()).decode()


def _logo_base64() -> str:
    return _img_b64("logo.png")


def _src_img(b64: str, size: int = 28) -> str:
    """Devuelve <img> inline con logo de fuente, o '' si no hay imagen."""
    if not b64:
        return ""
    return f'<img src="data:image/png;base64,{b64}" style="width:{size}px;height:{size}px;object-fit:contain;vertical-align:middle;border-radius:6px;" />'


def generar_pdf(resultado: dict) -> bytes:
    """
    Genera un PDF profesional a partir de un resultado de verificación.

    resultado debe tener: cedula, nombre, semaforo, bachiller, satje.
    """
    cedula     = resultado.get("cedula", "")
    sem        = resultado.get("semaforo", "") or ""
    bachiller  = resultado.get("bachiller") or {}
    satje      = resultado.get("satje") or {}
    setec      = resultado.get("setec") or {}
    fiscalia   = resultado.get("fiscalia") or {}
    notas      = (resultado.get("notas") or "").strip()

    # Cadena de fallback para el nombre, por si el cache/historial es antiguo:
    #   resultado.nombre → bachiller → SATJE → SETEC → "—"
    nombre = (
        resultado.get("nombre", "") or
        bachiller.get("nombre", "") or
        satje.get("nombre", "") or
        setec.get("nombre", "") or
        "—"
    )

    timestamp  = int(time.time())
    # Usar timezone Ecuador para que el PDF muestre hora local correcta
    fecha_str  = datetime.fromtimestamp(timestamp, tz=_TZ_EC).strftime("%d de %B de %Y · %H:%M")
    codigo_ver = _hash_verificacion(cedula, timestamp)

    # Registrar el código para que sea verificable después
    try:
        registrar_verificacion(codigo_ver, cedula, nombre, sem, timestamp)
    except Exception as e:
        print(f"[pdf] no se pudo registrar código de verificación: {e}")

    # QR ahora apunta a una URL real de verificación pública
    url_verificacion = f"{_PUBLIC_URL}/verificar/{codigo_ver}"
    qr_b64     = _qr_base64(url_verificacion)
    logo_b64   = _logo_base64()

    # Logos de fuentes oficiales
    logo_mineduc = _img_b64("logos/logo-mineduc-mark.png")
    logo_cj      = _img_b64("logos/logo-cj-mark.png")
    logo_setec   = _img_b64("logos/logo-setec-mark.png")
    logo_fge     = _img_b64("logos/logo-fge-mark.png")

    # Color del banner según nivel
    nivel_color = {
        "APTO":         "#10b981",
        "OBSERVACIÓN":  "#f59e0b",
        "RECHAZAR":     "#ef4444",
        "CRÍTICO":      "#7f1d1d",
        "SIN DATOS":    "#94a3b8",
    }
    color = "#0F2C5C"
    for k, v in nivel_color.items():
        if k in sem:
            color = v
            break

    # Generar HTML
    html = _construir_html(
        cedula=cedula, nombre=nombre, sem=sem, color=color,
        bachiller=bachiller, satje=satje, setec=setec, fiscalia=fiscalia,
        fecha_str=fecha_str, codigo_ver=codigo_ver,
        qr_b64=qr_b64, logo_b64=logo_b64,
        logo_mineduc=logo_mineduc, logo_cj=logo_cj,
        logo_setec=logo_setec, logo_fge=logo_fge,
        notas=notas,
    )

    # Renderizar a PDF
    pdf_bytes = HTML(string=html).write_pdf(stylesheets=[CSS(string=_CSS)])
    return pdf_bytes


def _construir_html(cedula, nombre, sem, color, bachiller, satje, setec, fiscalia,
                    fecha_str, codigo_ver, qr_b64, logo_b64,
                    logo_mineduc="", logo_cj="", logo_setec="", logo_fge="",
                    notas="") -> str:

    def _src_header(logo_b64_str: str, title: str, subtitle: str) -> str:
        """Cabecera de sección con logo de fuente oficial."""
        ico = _src_img(logo_b64_str, 26)
        return f"""<div class="seccion-titulo">
            <table style="width:100%;border-collapse:collapse;">
                <tr>
                    <td style="width:34px;vertical-align:middle;padding-right:10px;">{ico}</td>
                    <td style="vertical-align:middle;">
                        <div style="font-size:10.5pt;font-weight:700;color:#0F2C5C;line-height:1.2;">{title}</div>
                        <div style="font-size:7.5pt;color:#7B8794;margin-top:1px;">{subtitle}</div>
                    </td>
                </tr>
            </table>
        </div>"""

    # Sección bachiller
    bach_html = ""
    if bachiller:
        estado_b = bachiller.get("estado", "")
        hdr_b = _src_header(logo_mineduc, "Bachiller", "Ministerio de Educación del Ecuador")
        if estado_b == "ENCONTRADO":
            bach_html = f"""
            <div class="seccion">
                {hdr_b}
                <div class="caja verde">
                    <div class="caja-titulo">✓ Título confirmado</div>
                    <div class="caja-grid">
                        <div><div class="lbl">Título</div><div class="val">{bachiller.get('titulo', '—')}</div></div>
                        <div><div class="lbl">Especialidad</div><div class="val">{bachiller.get('especialidad', '—') or '—'}</div></div>
                        <div class="full"><div class="lbl">Institución</div><div class="val">{bachiller.get('institucion', '—') or '—'}</div></div>
                        <div><div class="lbl">Año de grado</div><div class="val">{(bachiller.get('fecha_grado') or '—')[:4]}</div></div>
                    </div>
                </div>
            </div>"""
        elif estado_b == "NO_ENCONTRADO":
            bach_html = f"""
            <div class="seccion">
                {hdr_b}
                <div class="caja amarilla">
                    <div class="caja-titulo">Sin registro de bachillerato</div>
                    <div>No existe título de bachiller registrado oficialmente para esta cédula.</div>
                </div>
            </div>"""
        else:
            bach_html = f"""
            <div class="seccion">
                {hdr_b}
                <div class="caja gris">
                    <div class="caja-titulo">Error de consulta</div>
                    <div>{bachiller.get('detalle', 'No se pudo completar la consulta')}</div>
                </div>
            </div>"""

    # Sección SATJE
    satje_html = ""
    if satje:
        estado_s = satje.get("estado", "")
        hdr_s = _src_header(logo_cj, "Procesos Judiciales", "Consejo de la Judicatura — SATJE")
        if estado_s == "SIN_PROCESOS":
            satje_html = f"""
            <div class="seccion">
                {hdr_s}
                <div class="caja verde">
                    <div class="caja-titulo">Sin procesos judiciales</div>
                    <div>No tiene causas activas como demandado ni como actor.</div>
                </div>
            </div>"""
        elif estado_s == "TIENE_PROCESOS":
            td = satje.get("total_demandado", 0)
            ta = satje.get("total_actor", 0)
            delitos = satje.get("delitos", [])

            delitos_html = ""
            if delitos:
                items = "".join(f"<li>{d}</li>" for d in delitos)
                delitos_html = f"""
                <div class="caja roja" style="margin-top:8px;">
                    <div class="caja-titulo">Delitos detectados</div>
                    <ul class="delitos">{items}</ul>
                </div>"""

            satje_html = f"""
            <div class="seccion">
                {hdr_s}
                <div class="stats-grid">
                    <div class="stat-box {'rojo' if td > 0 else 'gris'}">
                        <div class="stat-num">{td}</div>
                        <div class="stat-lbl">COMO DEMANDADO</div>
                    </div>
                    <div class="stat-box {'amarillo' if ta > 0 else 'gris'}">
                        <div class="stat-num">{ta}</div>
                        <div class="stat-lbl">COMO ACTOR</div>
                    </div>
                </div>
                {delitos_html}
            </div>"""
        else:
            satje_html = f"""
            <div class="seccion">
                {hdr_s}
                <div class="caja gris">
                    <div class="caja-titulo">Error de consulta</div>
                    <div>{satje.get('detalle', 'No se pudo completar la consulta')}</div>
                </div>
            </div>"""

    # Sección SETEC
    setec_html = ""
    if setec:
        estado_st = setec.get("estado", "")
        hdr_st = _src_header(logo_setec, "Capacitaciones Oficiales", "SETEC — Ministerio del Trabajo del Ecuador")
        if estado_st == "TIENE_CERTIFICADOS":
            cursos = setec.get("cursos", []) or []
            total = setec.get("total", len(cursos))
            items = "".join(f"<li>{c}</li>" for c in cursos)
            setec_html = f"""
            <div class="seccion">
                {hdr_st}
                <div class="caja verde">
                    <div class="caja-titulo">{total} certificación{'es' if total != 1 else ''} registrada{'s' if total != 1 else ''}</div>
                    <ul class="cursos">{items}</ul>
                </div>
            </div>"""
        elif estado_st == "SIN_CERTIFICADOS":
            setec_html = f"""
            <div class="seccion">
                {hdr_st}
                <div class="caja gris">
                    <div class="caja-titulo">Sin certificaciones registradas</div>
                    <div>No tiene cursos registrados en el sistema SETEC.</div>
                </div>
            </div>"""
        else:
            setec_html = f"""
            <div class="seccion">
                {hdr_st}
                <div class="caja gris">
                    <div class="caja-titulo">Error de consulta</div>
                    <div>{setec.get('detalle', 'No se pudo completar la consulta')}</div>
                </div>
            </div>"""

    # Sección Fiscalía
    fiscalia_html = ""
    if fiscalia:
        estado_f   = fiscalia.get("estado", "")
        noticias   = fiscalia.get("noticias") or []
        sospechoso = fiscalia.get("como_sospechoso", 0)
        denunciante = fiscalia.get("como_denunciante", 0)
        hdr_f = _src_header(logo_fge, "Noticias del Delito", "SIAF — Fiscalía General del Estado")

        if estado_f == "ERROR":
            fiscalia_html = f"""
            <div class="seccion">
                {hdr_f}
                <div class="caja gris">
                    <div class="caja-titulo">Error de consulta</div>
                    <div>{fiscalia.get('detalle', 'No se pudo completar la consulta')}</div>
                </div>
            </div>"""
        elif estado_f == "SIN_ANTECEDENTES":
            fiscalia_html = f"""
            <div class="seccion">
                {hdr_f}
                <div class="caja verde">
                    <div class="caja-titulo">Sin antecedentes en Fiscalía</div>
                    <div>No aparece en noticias del delito como sospechoso ni imputado.</div>
                </div>
            </div>"""
        else:
            filas_noticias = ""
            for n in noticias:
                rol = n.get("rol", "")
                clase_rol = "badge-rojo" if rol in ("SOSPECHOSO", "IMPUTADO", "PROCESADO", "ACUSADO", "SENTENCIADO", "INVESTIGADO") else "badge-amarillo"
                filas_noticias += f"""
                <tr>
                    <td>{n.get('delito') or '—'}</td>
                    <td>{n.get('fecha') or '—'}</td>
                    <td>{n.get('lugar') or '—'}</td>
                    <td><span class="{clase_rol}">{rol}</span></td>
                </tr>"""

            resumen = ""
            if sospechoso > 0:
                resumen = f"Aparece como <strong>sospechoso/imputado en {sospechoso} noticia(s)</strong>."
            elif denunciante > 0:
                resumen = f"Aparece como denunciante/víctima en {denunciante} noticia(s)."

            caja_clase = "roja" if sospechoso > 0 else "amarilla"

            fiscalia_html = f"""
            <div class="seccion">
                {hdr_f}
                <div class="caja {caja_clase}">
                    <div class="caja-titulo">{resumen}</div>
                </div>
                <table class="tabla-noticias">
                    <thead><tr><th>Delito</th><th>Fecha</th><th>Lugar</th><th>Rol</th></tr></thead>
                    <tbody>{filas_noticias}</tbody>
                </table>
            </div>"""

    logo_html = f'<img src="data:image/png;base64,{logo_b64}" class="logo-img"/>' if logo_b64 else ""

    # Footer dinámico: solo listar fuentes que realmente fueron consultadas
    fuentes_usadas = []
    if bachiller:
        fuentes_usadas.append("Ministerio de Educación")
    if satje:
        fuentes_usadas.append("Función Judicial (SATJE)")
    if setec:
        fuentes_usadas.append("SETEC (Min. Trabajo)")
    if fiscalia:
        fuentes_usadas.append("Fiscalía General del Estado (SIAF)")
    fuentes_str = " · ".join(fuentes_usadas) if fuentes_usadas else "JR Verifica EC"

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head><body>

<table class="header-table">
    <tr>
        <td class="hdr-logo">{logo_html}</td>
        <td class="hdr-brand">
            <div class="brand">JR Verifica EC</div>
            <div class="brand-sub">Verificación de antecedentes oficiales · Powered by JR Automata</div>
        </td>
        <td class="hdr-codigo">
            <div class="codigo-lbl">Código de verificación</div>
            <div class="codigo">{codigo_ver}</div>
        </td>
    </tr>
</table>
<div class="header-line"></div>

<div class="veredicto" style="background-color: {color};">
    <div class="veredicto-lbl">VEREDICTO</div>
    <div class="veredicto-val">{sem or 'CONSULTA INDIVIDUAL'}</div>
</div>

<div class="datos-box">
    <div class="datos-grid">
        <div>
            <div class="lbl">Cédula consultada</div>
            <div class="cedula-val">{cedula}</div>
        </div>
        <div>
            <div class="lbl">Nombre oficial</div>
            <div class="nombre-val">{nombre}</div>
        </div>
    </div>
</div>

{bach_html}
{satje_html}
{setec_html}
{fiscalia_html}

{f'''<div class="seccion notas-block">
    <div class="seccion-titulo" style="border-color:#7C5CE0;">
        <div style="font-size:10.5pt;font-weight:700;color:#5B4BE3;">📝 Notas del operador</div>
    </div>
    <div class="caja" style="background:#F4F0FE;border-color:#C5B8F2;color:#2C2480;white-space:pre-wrap;">{notas.replace('<','&lt;').replace('>','&gt;')}</div>
</div>''' if notas else ''}

<div class="footer">
    <div class="footer-left">
        <div><strong>Fecha y hora:</strong> {fecha_str}</div>
        <div><strong>Fuentes:</strong> {fuentes_str}</div>
        <div><strong>Validación:</strong> Documento generado automáticamente. Verifique con el código <strong>{codigo_ver}</strong>.</div>
    </div>
    <div class="footer-right">
        <img src="data:image/png;base64,{qr_b64}" class="qr-img"/>
        <div class="qr-lbl">Escanee para verificar</div>
    </div>
</div>

</body></html>"""


_CSS = """
@page {
    size: A4;
    margin: 1.4cm 1.6cm 1.4cm 1.6cm;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Helvetica', 'Arial', sans-serif; color: #1C2833; font-size: 10pt; }

/* Header — usamos tabla porque flexbox da problemas en WeasyPrint */
.header-table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 4px;
}
.hdr-logo { width: 60px; vertical-align: middle; padding-right: 16px; }
.hdr-brand { vertical-align: middle; }
.hdr-codigo { vertical-align: middle; text-align: right; width: 180px; }
.logo-img { height: 50px; width: 50px; object-fit: contain; display: block; }
.brand { font-size: 18pt; font-weight: bold; color: #0F2C5C; letter-spacing: -0.5px; line-height: 1.1; }
.brand-sub { font-size: 8pt; color: #7B7D7D; margin-top: 4px; line-height: 1.3; }
.codigo-lbl { font-size: 7pt; color: #7B7D7D; text-transform: uppercase; letter-spacing: 1px; }
.codigo { font-family: 'Courier', monospace; font-size: 11pt; font-weight: bold; color: #0F2C5C; letter-spacing: 1px; }
.header-line { border-bottom: 2px solid #0F2C5C; margin-bottom: 16px; padding-top: 8px; }

/* Veredicto */
.veredicto {
    color: white;
    padding: 18px 20px;
    border-radius: 8px;
    margin-bottom: 14px;
    text-align: center;
}
.veredicto-lbl { font-size: 8pt; opacity: 0.85; text-transform: uppercase; letter-spacing: 2px; }
.veredicto-val { font-size: 22pt; font-weight: bold; margin-top: 4px; letter-spacing: -0.5px; }

/* Datos */
.datos-box {
    background: #F4F6F7;
    border-radius: 8px;
    padding: 14px 18px;
    margin-bottom: 14px;
}
.datos-grid { display: flex; gap: 30px; }
.datos-grid > div { flex: 1; }
.lbl { font-size: 7pt; color: #7B7D7D; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px; }
.cedula-val { font-family: 'Courier', monospace; font-size: 13pt; font-weight: bold; color: #0F2C5C; letter-spacing: 1px; }
.nombre-val { font-size: 12pt; font-weight: bold; color: #1C2833; }

/* Secciones */
.seccion { margin-bottom: 16px; }
.seccion-titulo { margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1.5px solid #E8ECF0; }

/* Cajas */
.caja { padding: 12px 14px; border-radius: 6px; border: 1px solid; }
.caja.verde    { background: #D1FAE5; border-color: #6EE7B7; color: #065F46; }
.caja.amarilla { background: #FEF3C7; border-color: #FCD34D; color: #92400E; }
.caja.roja     { background: #FEE2E2; border-color: #FCA5A5; color: #991B1B; }
.caja.gris     { background: #F1F5F9; border-color: #CBD5E1; color: #475569; }
.caja-titulo { font-weight: bold; font-size: 10pt; margin-bottom: 6px; }
.caja-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 20px; margin-top: 8px; }
.caja-grid .full { grid-column: span 2; }
.caja-grid .val { font-weight: bold; font-size: 10pt; }

/* Stats */
.stats-grid { display: flex; gap: 10px; margin-top: 4px; }
.stat-box { flex: 1; text-align: center; padding: 14px 8px; border-radius: 6px; border: 1px solid; }
.stat-box.rojo     { background: #FEE2E2; border-color: #FCA5A5; }
.stat-box.amarillo { background: #FEF3C7; border-color: #FCD34D; }
.stat-box.gris     { background: #F1F5F9; border-color: #CBD5E1; }
.stat-num { font-size: 24pt; font-weight: bold; color: #0F2C5C; }
.stat-box.rojo .stat-num { color: #991B1B; }
.stat-box.amarillo .stat-num { color: #92400E; }
.stat-box.gris .stat-num { color: #64748B; }
.stat-lbl { font-size: 7pt; text-transform: uppercase; letter-spacing: 1px; margin-top: 4px; color: #64748B; }

/* Lista delitos */
.delitos { padding-left: 18px; margin-top: 4px; }
.delitos li { margin-bottom: 2px; font-size: 9pt; }

/* Lista cursos SETEC */
.cursos { padding-left: 18px; margin-top: 6px; }
.cursos li { margin-bottom: 3px; font-size: 9pt; font-weight: 600; }

/* Tabla noticias Fiscalía */
.tabla-noticias { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 9pt; }
.tabla-noticias th { background: #0F2C5C; color: white; padding: 6px 8px; text-align: left; font-size: 8pt; text-transform: uppercase; letter-spacing: 0.5px; }
.tabla-noticias td { padding: 6px 8px; border-bottom: 1px solid #E2E8F0; vertical-align: middle; }
.tabla-noticias tr:nth-child(even) td { background: #F8FAFC; }
.badge-rojo    { background: #FEE2E2; color: #991B1B; border: 1px solid #FCA5A5; border-radius: 3px; padding: 2px 6px; font-size: 7pt; font-weight: bold; text-transform: uppercase; }
.badge-amarillo { background: #FEF3C7; color: #92400E; border: 1px solid #FCD34D; border-radius: 3px; padding: 2px 6px; font-size: 7pt; font-weight: bold; text-transform: uppercase; }

/* Footer */
.footer {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-top: 22px;
    padding-top: 12px;
    border-top: 1px solid #D5D8DC;
    font-size: 8pt;
    color: #64748B;
}
.footer-left { flex: 1; line-height: 1.6; }
.footer-left > div { margin-bottom: 2px; }
.footer-right { text-align: center; margin-left: 14px; }
.qr-img { width: 80px; height: 80px; }
.qr-lbl { font-size: 7pt; margin-top: 2px; }
"""
