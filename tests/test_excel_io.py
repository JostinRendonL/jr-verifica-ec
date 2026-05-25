"""Tests del lector de Excel (detección flexible de columnas + dedupe)."""
from io import BytesIO
from openpyxl import Workbook
import pytest

from src.excel_io import leer_cedulas


def _build_xlsx(rows: list[list]) -> bytes:
    """Helper: convierte lista de filas en xlsx bytes."""
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestDeteccionColumnas:
    def test_header_cedula_y_nombre_estandar(self):
        xlsx = _build_xlsx([
            ["cedula", "nombre"],
            ["0954008272", "Jostin"],
            ["1310009999", "Fulano"],
        ])
        items, errores = leer_cedulas(xlsx)
        assert errores == []
        assert len(items) == 2
        assert items[0]["cedula"] == "0954008272"
        assert items[0]["nombre"] == "Jostin"

    def test_header_con_acento(self):
        xlsx = _build_xlsx([
            ["Cédula", "Nombre Completo"],
            ["0954008272", "Jostin Rendón"],
        ])
        items, _ = leer_cedulas(xlsx)
        assert items[0]["nombre"] == "Jostin Rendón"

    def test_header_apellidos_y_nombres(self):
        xlsx = _build_xlsx([
            ["N° Identificación", "Apellidos y Nombres"],
            ["0954008272", "RENDÓN JOSTIN"],
        ])
        items, _ = leer_cedulas(xlsx)
        assert len(items) == 1
        assert items[0]["nombre"] == "RENDÓN JOSTIN"

    def test_header_solo_ci(self):
        xlsx = _build_xlsx([
            ["CI", "Apellido"],
            ["0954008272", "Pérez"],
        ])
        items, _ = leer_cedulas(xlsx)
        assert len(items) == 1

    def test_sin_header_asume_col_a_y_b(self):
        xlsx = _build_xlsx([
            ["0954008272", "Sin Header"],
            ["1310009999", "Otro"],
        ])
        items, _ = leer_cedulas(xlsx)
        assert len(items) == 2
        assert items[0]["nombre"] == "Sin Header"


class TestDedupe:
    def test_cedulas_duplicadas_se_unifican(self):
        xlsx = _build_xlsx([
            ["cedula", "nombre"],
            ["0954008272", "Jostin"],
            ["0954008272", "Jostin"],   # duplicada exacta
            ["0954008272", ""],          # duplicada sin nombre
        ])
        items, _ = leer_cedulas(xlsx)
        assert len(items) == 1
        assert items[0]["nombre"] == "Jostin"

    def test_dedupe_conserva_nombre_no_vacio(self):
        xlsx = _build_xlsx([
            ["cedula", "nombre"],
            ["0954008272", ""],
            ["0954008272", "Jostin"],   # segunda aparición tiene nombre
            ["0954008272", "Otro"],     # tercera con otro nombre
        ])
        items, _ = leer_cedulas(xlsx)
        assert len(items) == 1
        # Conserva el primer nombre no vacío
        assert items[0]["nombre"] == "Jostin"


class TestPadding:
    def test_cedula_con_menos_de_10_digitos_se_pad_con_ceros(self):
        xlsx = _build_xlsx([
            ["cedula"],
            ["954008272"],     # 9 dígitos
        ])
        items, _ = leer_cedulas(xlsx)
        assert items[0]["cedula"] == "0954008272"

    def test_cedula_vacia_se_ignora(self):
        xlsx = _build_xlsx([
            ["cedula", "nombre"],
            ["", "Vacía"],
            ["0954008272", "Buena"],
        ])
        items, _ = leer_cedulas(xlsx)
        assert len(items) == 1
        assert items[0]["cedula"] == "0954008272"
