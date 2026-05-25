"""Tests del flujo de reset por email + tokens."""
import time
import pytest

from src import password_reset, usuarios


@pytest.fixture(autouse=True)
def _setup():
    """Limpiar usuarios y tokens entre tests."""
    usuarios.init_db()
    password_reset.init_db()
    conn = password_reset._get_conn()
    with password_reset._write_lock:
        conn.execute("DELETE FROM password_resets")
    with usuarios._write_lock:
        usuarios._get_conn().execute("DELETE FROM usuarios")
    yield
    with password_reset._write_lock:
        conn.execute("DELETE FROM password_resets")
    with usuarios._write_lock:
        usuarios._get_conn().execute("DELETE FROM usuarios")


class TestGenerarToken:
    def test_genera_y_valida(self):
        u = usuarios.crear_usuario("a@ex.com", "Ana", "password123")
        t = password_reset.generar_token(u.id)
        assert isinstance(t, str)
        assert len(t) >= 32   # token largo
        info = password_reset.validar_token(t)
        assert info is not None
        assert info.usuario_id == u.id
        assert info.usado is False

    def test_token_invalido(self):
        assert password_reset.validar_token("token-falso-xxxxxxxxxxxxxxxx") is None
        assert password_reset.validar_token("") is None

    def test_no_persiste_token_plano(self):
        """Crítico: la DB debe guardar SOLO el hash, no el token."""
        u = usuarios.crear_usuario("a@ex.com", "Ana", "password123")
        t = password_reset.generar_token(u.id)
        conn = password_reset._get_conn()
        row = conn.execute("SELECT token_hash FROM password_resets").fetchone()
        assert row["token_hash"] != t   # no es el plano
        assert len(row["token_hash"]) == 64   # SHA-256 hex
        # Pero validar_token aún funciona porque calcula el hash internamente
        assert password_reset.validar_token(t) is not None

    def test_token_unico_por_call(self):
        u = usuarios.crear_usuario("a@ex.com", "Ana", "password123")
        t1 = password_reset.generar_token(u.id)
        t2 = password_reset.generar_token(u.id)
        assert t1 != t2


class TestUsoYExpiracion:
    def test_marcar_usado(self):
        u = usuarios.crear_usuario("a@ex.com", "Ana", "password123")
        t = password_reset.generar_token(u.id)
        assert password_reset.marcar_usado(t) is True
        # Segunda vez ya no debe devolver True
        assert password_reset.marcar_usado(t) is False
        # Token ya no es válido
        assert password_reset.validar_token(t) is None

    def test_token_expirado(self):
        u = usuarios.crear_usuario("a@ex.com", "Ana", "password123")
        # TTL de 0 → ya expirado al instante
        t = password_reset.generar_token(u.id, ttl_seg=0)
        time.sleep(0.01)
        assert password_reset.validar_token(t) is None

    def test_invalidar_todos_los_tokens(self):
        u = usuarios.crear_usuario("a@ex.com", "Ana", "password123")
        t1 = password_reset.generar_token(u.id)
        t2 = password_reset.generar_token(u.id)
        t3 = password_reset.generar_token(u.id)
        n = password_reset.invalidar_tokens_de_usuario(u.id)
        assert n == 3
        for t in (t1, t2, t3):
            assert password_reset.validar_token(t) is None


class TestLimpieza:
    def test_limpia_expirados(self):
        u = usuarios.crear_usuario("a@ex.com", "Ana", "password123")
        password_reset.generar_token(u.id, ttl_seg=0)
        password_reset.generar_token(u.id, ttl_seg=0)
        # Uno vigente
        t_vigente = password_reset.generar_token(u.id, ttl_seg=3600)
        time.sleep(0.01)
        n = password_reset.limpiar_expirados()
        assert n == 2
        # El vigente sobrevive
        assert password_reset.validar_token(t_vigente) is not None


class TestIntegracionConUsuario:
    def test_flujo_completo_reset(self):
        """Simula el flujo end-to-end: olvido → token → nueva pass → puede loguearse."""
        u = usuarios.crear_usuario("user@ex.com", "User", "pass-vieja-12345")
        assert usuarios.autenticar("user@ex.com", "pass-vieja-12345") is not None

        # Olvido pass → genera token
        token = password_reset.generar_token(u.id, ip_origen="1.2.3.4")
        info = password_reset.validar_token(token)
        assert info.usuario_id == u.id

        # Setea nueva pass
        usuarios.cambiar_password(info.usuario_id, "pass-nueva-segura")
        password_reset.marcar_usado(token)

        # Vieja ya no funciona, nueva sí
        assert usuarios.autenticar("user@ex.com", "pass-vieja-12345") is None
        assert usuarios.autenticar("user@ex.com", "pass-nueva-segura") is not None
        # Token quedó inútil
        assert password_reset.validar_token(token) is None
