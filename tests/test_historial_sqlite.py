"""Tests del backend SQLite de historial."""
import time
import pytest
from src import historial_sqlite as h


def _resultado_apto(cedula="0954008272", nombre="JOSTIN RENDON"):
    return {
        "cedula":   cedula,
        "nombre":   nombre,
        "semaforo": "🟢 APTO",
        "bachiller": {"estado": "ENCONTRADO", "institucion": "UE Test"},
        "satje":     {"estado": "SIN_PROCESOS", "total_demandado": 0,
                      "total_actor": 0, "delitos": []},
    }


def _resultado_rechazar(cedula="1310009999"):
    return {
        "cedula":   cedula,
        "nombre":   "FULANO TEST",
        "semaforo": "🔴 RECHAZAR",
        "bachiller": {"estado": "NO_ENCONTRADO"},
        "satje":     {"estado": "TIENE_PROCESOS", "total_demandado": 2,
                      "total_actor": 0, "delitos": ["ROBO", "ESTAFA"]},
    }


class TestRegistrarYBuscar:
    def test_buscar_vacio(self):
        assert h.buscar_cache("0954008272", "completo") is None

    def test_registrar_y_buscar(self):
        r = _resultado_apto()
        h.registrar(r, "completo")
        cached = h.buscar_cache("0954008272", "completo")
        assert cached is not None
        assert cached["nombre"] == "JOSTIN RENDON"

    def test_buscar_subtipo_fallback_a_completo(self):
        # Si pides "bachiller" y solo hay "completo" guardado, debe devolverlo
        h.registrar(_resultado_apto(), "completo")
        cached = h.buscar_cache("0954008272", "bachiller")
        assert cached is not None
        assert cached["nombre"] == "JOSTIN RENDON"

    def test_buscar_cedula_inexistente(self):
        h.registrar(_resultado_apto(), "completo")
        assert h.buscar_cache("0000000000", "completo") is None

    def test_total_entradas_incrementa(self):
        assert h.total_entradas() == 0
        h.registrar(_resultado_apto("1310007654"), "satje")
        h.registrar(_resultado_apto("1310007655"), "bachiller")
        assert h.total_entradas() == 2


class TestListar:
    def test_listar_vacio(self):
        assert h.listar() == []

    def test_listar_orden_por_recientes(self):
        h.registrar(_resultado_apto("1234567893"), "completo")  # cédula válida
        time.sleep(0.01)
        h.registrar(_resultado_apto("1310009999"), "completo")
        # La más reciente primero
        lista = h.listar()
        assert len(lista) == 2

    def test_listar_filtro_cedula(self):
        h.registrar(_resultado_apto("0954008272"), "completo")
        h.registrar(_resultado_apto("1310009999"), "completo")
        filtrada = h.listar(filtro_cedula="0954")
        assert len(filtrada) == 1
        assert filtrada[0]["cedula"] == "0954008272"

    def test_listar_filtro_semaforo(self):
        h.registrar(_resultado_apto(),     "completo")
        h.registrar(_resultado_rechazar(), "completo")
        aptos = h.listar(filtro_semaforo="APTO")
        assert len(aptos) == 1
        assert "APTO" in aptos[0]["semaforo"]


class TestBorrar:
    def test_borrar_entrada(self):
        h.registrar(_resultado_apto(), "completo")
        entradas = h.listar()
        assert len(entradas) == 1
        eid = entradas[0]["id"]
        assert h.borrar_entrada(eid) is True
        assert h.total_entradas() == 0

    def test_borrar_entrada_inexistente(self):
        assert h.borrar_entrada("xxxxxxxxx") is False

    def test_borrar_por_cedula_borra_todas(self):
        h.registrar(_resultado_apto(),                   "bachiller")
        h.registrar(_resultado_apto(),                   "completo")
        h.registrar(_resultado_apto("1310009999"),       "completo")
        n = h.borrar_por_cedula("0954008272")
        assert n == 2
        assert h.total_entradas() == 1   # solo la otra cédula sobrevive

    def test_limpiar_todo(self):
        h.registrar(_resultado_apto(), "completo")
        h.registrar(_resultado_rechazar(), "completo")
        n = h.limpiar_todo()
        assert n == 2
        assert h.total_entradas() == 0


class TestBorrarAntiguos:
    def test_borra_solo_los_viejos(self, monkeypatch):
        # Hack: insertar directo con timestamp viejo
        import sqlite3, json
        conn = h._get_conn()
        viejo = int(time.time()) - (13 * 30 * 86400)   # 13 meses atrás
        with h._write_lock:
            conn.execute(
                "INSERT INTO historial (id, cedula, tipo, timestamp, semaforo, nombre, resultado_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("vieja", "1310007654", "completo", viejo, "APTO", "VIEJO", json.dumps({}))
            )
        h.registrar(_resultado_apto(), "completo")    # entrada reciente
        assert h.total_entradas() == 2

        n = h.borrar_antiguos(meses=12)
        assert n == 1
        assert h.total_entradas() == 1

    def test_meses_cero_no_hace_nada(self):
        h.registrar(_resultado_apto(), "completo")
        assert h.borrar_antiguos(meses=0) == 0


class TestStats:
    def test_stats_vacio(self):
        s = h.calcular_stats()
        assert s["total"] == 0
        assert s["niveles"] == {"APTO": 0, "OBSERVACIÓN": 0, "RECHAZAR": 0,
                                "CRÍTICO": 0, "SIN DATOS": 0, "OTROS": 0}

    def test_stats_cuenta_niveles_correctamente(self):
        h.registrar(_resultado_apto(),     "completo")
        h.registrar(_resultado_apto("1310007654"), "completo")
        h.registrar(_resultado_rechazar(), "completo")
        s = h.calcular_stats()
        assert s["total"] == 3
        assert s["niveles"]["APTO"]     == 2
        assert s["niveles"]["RECHAZAR"] == 1
