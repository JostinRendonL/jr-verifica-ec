"""Tests de los extractores de bg_client (parsing del raw bg-api → dict normalizado)."""
import pytest
from src.bg_client import extraer_bachiller, extraer_satje, extraer_setec


class TestExtraerBachiller:
    def test_no_ok(self):
        r = extraer_bachiller({"ok": False, "error": "timeout"})
        assert r["estado"] == "ERROR"
        assert "timeout" in r["detalle"]

    def test_encontrado_directo(self):
        raw = {
            "ok": True,
            "estado": "ENCONTRADO",
            "nombre": "JOSTIN RENDON",
            "titulo": "Bachiller en Comercio",
            "especialidad": "Contabilidad",
            "institucion": "UE Modelo",
            "fecha_grado": "2010-06-15",
            "tiene_titulo": True,
        }
        r = extraer_bachiller(raw)
        assert r["estado"] == "ENCONTRADO"
        assert r["nombre"] == "JOSTIN RENDON"
        assert r["titulo"] == "Bachiller en Comercio"
        assert r["institucion"] == "UE Modelo"

    def test_encontrado_via_completo(self):
        # /completo devuelve los datos anidados en .bachiller
        raw = {"ok": True, "bachiller": {
            "estado": "ENCONTRADO", "tiene_titulo": True,
            "nombre": "Maria", "titulo": "Bachiller", "institucion": "UE Test",
            "fecha_grado": "2015", "especialidad": "Ciencias",
        }}
        r = extraer_bachiller(raw)
        assert r["estado"] == "ENCONTRADO"
        assert r["nombre"] == "Maria"

    def test_no_encontrado(self):
        r = extraer_bachiller({"ok": True, "estado": "NO_ENCONTRADO"})
        assert r["estado"] == "NO_ENCONTRADO"
        assert "No existe" in r["detalle"]


class TestExtraerSatje:
    def test_no_ok(self):
        r = extraer_satje({"ok": False, "error": "503"})
        assert r["estado"] == "ERROR"

    def test_sin_procesos(self):
        raw = {"ok": True, "satje": {
            "total_demandado": 0, "total_actor": 0,
            "causas_demandado": [], "causas_actor": [],
        }}
        r = extraer_satje(raw)
        assert r["estado"] == "SIN_PROCESOS"
        assert r["total_demandado"] == 0
        assert r["nombre"] == ""

    def test_tiene_procesos_extrae_nombre_de_demandado(self):
        raw = {"ok": True, "satje": {
            "total_demandado": 2, "total_actor": 0,
            "causas_demandado": [
                {"delito": "144 HOMICIDIO", "nombreDemandado": "JUAN PEREZ"},
                {"delito": "ROBO", "nombreDemandado": "JUAN PEREZ"},
            ],
            "causas_actor": [],
        }}
        r = extraer_satje(raw)
        assert r["estado"] == "TIENE_PROCESOS"
        assert r["total_demandado"] == 2
        assert r["nombre"] == "JUAN PEREZ"
        # Verificar que se eliminó el prefijo numérico del delito
        assert "HOMICIDIO" in r["delitos"]
        assert "144 HOMICIDIO" not in r["delitos"]

    def test_extrae_nombre_de_actor_si_no_hay_demandado(self):
        raw = {"ok": True, "satje": {
            "total_demandado": 0, "total_actor": 1,
            "causas_demandado": [],
            "causas_actor": [{"nombreActor": "MARIA VICTIMA", "delito": "ROBO"}],
        }}
        r = extraer_satje(raw)
        assert r["nombre"] == "MARIA VICTIMA"


class TestExtraerSetec:
    def test_no_ok(self):
        r = extraer_setec({"ok": False, "error": "down"})
        assert r["estado"] == "ERROR"
        assert r["cursos"] == []

    def test_tiene_certificados_plano(self):
        # /consultar/setec devuelve data plana (sin clave "setec" anidada)
        raw = {
            "ok":                 True,
            "tiene_certificados": True,
            "detalle_cursos":     "CURSO A (60h) | CURSO B (40h)",
            "total_cursos":       2,
            "nombre":             "ANA TORRES",
        }
        r = extraer_setec(raw)
        assert r["estado"] == "TIENE_CERTIFICADOS"
        assert r["total"]  == 2
        assert r["nombre"] == "ANA TORRES"
        assert len(r["cursos"]) == 2

    def test_tiene_certificados_anidado_legacy(self):
        # Compatibilidad: si viene anidado en .setec
        raw = {"ok": True, "setec": {
            "tiene_certificados": True,
            "detalle_cursos": "CURSO X (10h)",
            "total_cursos": 1,
            "nombre": "PEDRO",
        }}
        r = extraer_setec(raw)
        assert r["estado"] == "TIENE_CERTIFICADOS"
        assert r["total"] == 1

    def test_sin_certificados(self):
        raw = {"ok": True, "tiene_certificados": False}
        r = extraer_setec(raw)
        assert r["estado"] == "SIN_CERTIFICADOS"
        assert r["cursos"] == []
        assert r["total"]  == 0
