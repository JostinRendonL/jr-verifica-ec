"""Tests de validación de cédula ecuatoriana."""
import pytest
from src.auth import cedula_valida_ec


class TestCedulaValidaEc:
    def test_cedula_valida_real(self):
        # Cédulas conocidas correctas (algoritmo del dígito verificador EC)
        assert cedula_valida_ec("0954008272") is True   # Jostin Rendón
        assert cedula_valida_ec("0925772246") is True   # AGUILAR JAIME DIANA
        assert cedula_valida_ec("0943725093") is True   # CAÑAS LEON EDUARDO

    def test_cedula_longitud_incorrecta(self):
        assert cedula_valida_ec("12345") is False
        assert cedula_valida_ec("12345678901") is False
        assert cedula_valida_ec("") is False
        assert cedula_valida_ec(None) is False

    def test_cedula_no_numerica(self):
        assert cedula_valida_ec("abcdefghij") is False
        assert cedula_valida_ec("095400827a") is False

    def test_cedula_provincia_invalida(self):
        # provincia debe ser 1-24 o 30 (digital ec)
        assert cedula_valida_ec("9954008272") is False   # provincia 99
        assert cedula_valida_ec("2554008272") is False   # provincia 25

    def test_cedula_tercer_digito_invalido(self):
        # tercer dígito >= 6 → inválido (no es persona natural)
        assert cedula_valida_ec("0964008272") is False
        assert cedula_valida_ec("0974008272") is False

    def test_digito_verificador_incorrecto(self):
        # cambiar último dígito de una válida → inválido
        assert cedula_valida_ec("0954008273") is False
        assert cedula_valida_ec("0954008270") is False
