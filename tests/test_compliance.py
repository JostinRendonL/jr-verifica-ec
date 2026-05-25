"""Tests del módulo compliance (LOPDP)."""
import time
import json
import uuid
import pytest
from src import compliance, historial_sqlite as h, verificaciones as v


def _seed_historial(cedula="0954008272", timestamp=None):
    """Inserta una entrada de prueba con timestamp configurable y id único."""
    ts = timestamp or int(time.time())
    conn = h._get_conn()
    with h._write_lock:
        conn.execute(
            "INSERT INTO historial (id, cedula, tipo, timestamp, semaforo, nombre, resultado_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"id_{uuid.uuid4().hex[:12]}", cedula, "completo", ts, "APTO", "X",
             json.dumps({"cedula": cedula}))
        )


def _seed_verificacion(codigo, cedula="0954008272", timestamp=None):
    ts = timestamp or int(time.time())
    v._store[codigo] = {"cedula": cedula, "nombre": "X", "semaforo": "APTO", "timestamp": ts}


@pytest.fixture(autouse=True)
def _limpiar_verificaciones():
    """Vaciar también las verificaciones entre tests."""
    v._store.clear()
    yield
    v._store.clear()


class TestDerechoAlOlvido:
    def test_cedula_vacia(self):
        r = compliance.derecho_al_olvido("")
        assert r["historial_borrado"] == 0
        assert r["verificaciones_borradas"] == 0

    def test_borra_todo_lo_de_una_cedula(self):
        _seed_historial("0954008272")
        _seed_historial("0954008272")        # 2 entradas
        _seed_historial("1310009999")        # otra cédula
        _seed_verificacion("AAA111", "0954008272")
        _seed_verificacion("BBB222", "0954008272")
        _seed_verificacion("CCC333", "1310009999")

        r = compliance.derecho_al_olvido("0954008272", motivo="Test")
        assert r["ok"] is True
        assert r["historial_borrado"] == 2
        assert r["verificaciones_borradas"] == 2

        # La otra cédula no se tocó
        assert h.total_entradas() == 1
        assert v.total() == 1


class TestEjecutarLimpieza:
    def test_no_hay_nada_que_borrar(self):
        r = compliance.ejecutar_limpieza(meses=12)
        assert r["ok"] is True
        assert r["historial_borrado"] == 0
        assert r["verificaciones_borradas"] == 0

    def test_borra_solo_los_viejos(self):
        ts_viejo  = int(time.time()) - (13 * 30 * 86400)
        ts_reciente = int(time.time())
        _seed_historial("0954008272", timestamp=ts_viejo)
        _seed_historial("1310009999", timestamp=ts_reciente)
        _seed_verificacion("VIEJO", "0954008272", timestamp=ts_viejo)
        _seed_verificacion("FRESCO", "1310009999", timestamp=ts_reciente)

        r = compliance.ejecutar_limpieza(meses=12)
        assert r["historial_borrado"] == 1
        assert r["verificaciones_borradas"] == 1

        # Los recientes sobreviven
        assert h.total_entradas() == 1
        assert v.total() == 1


class TestEstadisticasCompliance:
    def test_estructura_minima(self):
        stats = compliance.estadisticas_compliance()
        assert "retencion_meses" in stats
        assert "total_historial" in stats
        assert "total_verificaciones" in stats
        assert "scheduler" in stats
        # scheduler tiene esta estructura siempre
        assert "activo" in stats["scheduler"]
