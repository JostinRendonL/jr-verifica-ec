"""Tests del módulo de usuarios multi-tenant."""
import os
import pytest

from src import usuarios
from src.usuarios import (
    crear_usuario, autenticar, obtener_por_id, obtener_por_email,
    listar, existe_admin, desactivar, reactivar, cambiar_password,
    cambiar_rol, bootstrap_admin_si_falta,
    UsuarioError, MIN_PASSWORD_LEN,
)


@pytest.fixture(autouse=True)
def _limpiar_usuarios_entre_tests():
    """Borra la tabla usuarios entre tests para aislamiento."""
    usuarios.init_db()
    conn = usuarios._get_conn()
    with usuarios._write_lock:
        conn.execute("DELETE FROM usuarios")
    yield
    with usuarios._write_lock:
        conn.execute("DELETE FROM usuarios")


# ── crear_usuario ──────────────────────────────────────────────────────────
class TestCrearUsuario:
    def test_basico(self):
        u = crear_usuario("test@ex.com", "Test User", "password123")
        assert u.email == "test@ex.com"
        assert u.nombre == "Test User"
        assert u.rol == "operador"
        assert u.activo is True
        assert u.debe_cambiar_pass is False

    def test_email_normalizado_lowercase(self):
        u = crear_usuario("  Test@EXAMPLE.com  ", "Xu", "password123")
        assert u.email == "test@example.com"

    def test_admin_explicito(self):
        u = crear_usuario("a@ex.com", "Admin", "password123", rol="admin")
        assert u.rol == "admin"

    def test_email_invalido_falla(self):
        with pytest.raises(UsuarioError):
            crear_usuario("noemail", "X", "password123")
        with pytest.raises(UsuarioError):
            crear_usuario("", "X", "password123")

    def test_nombre_corto_falla(self):
        with pytest.raises(UsuarioError):
            crear_usuario("ok@ex.com", "A", "password123")

    def test_password_corto_falla(self):
        with pytest.raises(UsuarioError):
            crear_usuario("ok@ex.com", "User", "short")
        # justo en el límite
        with pytest.raises(UsuarioError):
            crear_usuario("ok@ex.com", "User", "a" * (MIN_PASSWORD_LEN - 1))

    def test_rol_invalido_falla(self):
        with pytest.raises(UsuarioError):
            crear_usuario("ok@ex.com", "User", "password123", rol="superuser")

    def test_email_duplicado_falla(self):
        crear_usuario("dup@ex.com", "User1", "password123")
        with pytest.raises(UsuarioError, match="ya registrado"):
            crear_usuario("DUP@EX.com", "User2", "password456")

    def test_debe_cambiar_pass_se_guarda(self):
        u = crear_usuario("nu@ex.com", "Nuevo", "password123", debe_cambiar_pass=True)
        assert u.debe_cambiar_pass is True


# ── autenticar ──────────────────────────────────────────────────────────────
class TestAutenticar:
    def test_credenciales_correctas(self):
        crear_usuario("a@ex.com", "Ana", "password123")
        u = autenticar("a@ex.com", "password123")
        assert u is not None
        assert u.email == "a@ex.com"

    def test_email_case_insensitive(self):
        crear_usuario("a@ex.com", "Ana", "password123")
        u = autenticar("A@EX.COM", "password123")
        assert u is not None

    def test_password_incorrecta(self):
        crear_usuario("a@ex.com", "Ana", "password123")
        assert autenticar("a@ex.com", "otra-pass-no") is None

    def test_usuario_inexistente(self):
        assert autenticar("nadie@ex.com", "password123") is None

    def test_usuario_desactivado_no_loguea(self):
        u = crear_usuario("d@ex.com", "Dani", "password123")
        # Forzar segundo admin para poder desactivar a Dani sin tropezar con
        # la regla "no se puede desactivar al último admin activo"
        crear_usuario("ad@ex.com", "Admin", "password123", rol="admin")
        cambiar_rol(u.id, "operador")
        desactivar(u.id)
        assert autenticar("d@ex.com", "password123") is None

    def test_actualiza_ultimo_login(self):
        u = crear_usuario("a@ex.com", "Ana", "password123")
        assert u.ultimo_login is None
        u2 = autenticar("a@ex.com", "password123")
        assert u2.ultimo_login is not None
        assert u2.ultimo_login > 0


# ── obtener / listar ────────────────────────────────────────────────────────
class TestObtenerListar:
    def test_obtener_por_id(self):
        u = crear_usuario("a@ex.com", "Ana", "password123")
        assert obtener_por_id(u.id).email == "a@ex.com"
        assert obtener_por_id("inexistente") is None
        assert obtener_por_id("") is None

    def test_obtener_por_email(self):
        crear_usuario("a@ex.com", "Ana", "password123")
        assert obtener_por_email("A@EX.COM") is not None
        assert obtener_por_email("nadie@ex.com") is None

    def test_listar_solo_activos(self):
        a = crear_usuario("a@ex.com", "Admin A", "password123", rol="admin")
        crear_usuario("b@ex.com", "Admin B", "password123", rol="admin")
        c = crear_usuario("c@ex.com", "Carlos", "password123")
        desactivar(c.id, ejecutor_id=a.id)
        activos = listar(solo_activos=True)
        emails = [u.email for u in activos]
        assert "c@ex.com" not in emails
        todos = listar(solo_activos=False)
        assert len(todos) == 3


# ── desactivar / reactivar ──────────────────────────────────────────────────
class TestDesactivar:
    def test_soft_delete(self):
        a = crear_usuario("a@ex.com", "Admin", "password123", rol="admin")
        b = crear_usuario("b@ex.com", "Beto", "password123")
        assert desactivar(b.id, ejecutor_id=a.id) is True
        assert obtener_por_id(b.id).activo is False

    def test_no_autodesactivar(self):
        a = crear_usuario("a@ex.com", "Admin", "password123", rol="admin")
        with pytest.raises(UsuarioError, match="propia"):
            desactivar(a.id, ejecutor_id=a.id)

    def test_no_desactivar_ultimo_admin(self):
        a = crear_usuario("a@ex.com", "Admin", "password123", rol="admin")
        # ejecutor es otro user (un operador), pero igual debe bloquear
        op = crear_usuario("op@ex.com", "Op", "password123")
        with pytest.raises(UsuarioError, match="último admin"):
            desactivar(a.id, ejecutor_id=op.id)

    def test_reactivar(self):
        a = crear_usuario("a@ex.com", "Admin", "password123", rol="admin")
        b = crear_usuario("b@ex.com", "Beto", "password123")
        desactivar(b.id, ejecutor_id=a.id)
        assert reactivar(b.id) is True
        assert obtener_por_id(b.id).activo is True


# ── cambiar_password ────────────────────────────────────────────────────────
class TestCambiarPassword:
    def test_cambio_funciona(self):
        u = crear_usuario("a@ex.com", "Ana", "password123")
        assert cambiar_password(u.id, "nueva-pass-segura") is True
        # vieja no funciona
        assert autenticar("a@ex.com", "password123") is None
        # nueva sí
        assert autenticar("a@ex.com", "nueva-pass-segura") is not None

    def test_password_corta_falla(self):
        u = crear_usuario("a@ex.com", "Ana", "password123")
        with pytest.raises(UsuarioError):
            cambiar_password(u.id, "short")

    def test_limpia_debe_cambiar_pass(self):
        u = crear_usuario("a@ex.com", "Ana", "password123", debe_cambiar_pass=True)
        assert u.debe_cambiar_pass is True
        cambiar_password(u.id, "nueva-pass-segura")
        assert obtener_por_id(u.id).debe_cambiar_pass is False


# ── cambiar_rol ─────────────────────────────────────────────────────────────
class TestCambiarRol:
    def test_promover_a_admin(self):
        crear_usuario("a@ex.com", "Admin", "password123", rol="admin")
        u = crear_usuario("o@ex.com", "Op", "password123")
        assert cambiar_rol(u.id, "admin") is True
        assert obtener_por_id(u.id).rol == "admin"

    def test_no_degradar_ultimo_admin(self):
        a = crear_usuario("a@ex.com", "Admin", "password123", rol="admin")
        with pytest.raises(UsuarioError, match="último admin"):
            cambiar_rol(a.id, "operador")

    def test_rol_invalido(self):
        u = crear_usuario("a@ex.com", "Xy", "password123")
        with pytest.raises(UsuarioError):
            cambiar_rol(u.id, "superduper")


# ── existe_admin ────────────────────────────────────────────────────────────
class TestExisteAdmin:
    def test_falso_inicialmente(self):
        assert existe_admin() is False

    def test_verdadero_si_hay_admin(self):
        crear_usuario("a@ex.com", "Admin", "password123", rol="admin")
        assert existe_admin() is True

    def test_falso_si_admin_desactivado_y_no_otros(self):
        # Necesitamos 2 admins para poder desactivar uno
        a1 = crear_usuario("a1@ex.com", "Admin1", "password123", rol="admin")
        a2 = crear_usuario("a2@ex.com", "Admin2", "password123", rol="admin")
        desactivar(a2.id, ejecutor_id=a1.id)
        assert existe_admin(activo=True) is True   # queda a1


# ── bootstrap_admin_si_falta ────────────────────────────────────────────────
class TestBootstrap:
    def test_crea_admin_desde_env(self, monkeypatch):
        monkeypatch.setenv("APP_PASSWORD", "super-secreto-12345")
        monkeypatch.setenv("ADMIN_EMAIL", "boss@empresa.com")
        monkeypatch.setenv("ADMIN_NOMBRE", "Jefe")
        u = bootstrap_admin_si_falta()
        assert u is not None
        assert u.email == "boss@empresa.com"
        assert u.nombre == "Jefe"
        assert u.rol == "admin"
        assert u.debe_cambiar_pass is False    # admin bootstrap NO requiere cambio

    def test_idempotente(self, monkeypatch):
        monkeypatch.setenv("APP_PASSWORD", "super-secreto-12345")
        u1 = bootstrap_admin_si_falta()
        u2 = bootstrap_admin_si_falta()   # segundo call
        assert u1 is not None
        assert u2 is None                  # no crea otro

    def test_no_crea_si_password_invalida(self, monkeypatch):
        monkeypatch.setenv("APP_PASSWORD", "cambiar")
        assert bootstrap_admin_si_falta() is None
        assert existe_admin() is False

    def test_no_crea_si_password_corta(self, monkeypatch):
        monkeypatch.setenv("APP_PASSWORD", "short")
        assert bootstrap_admin_si_falta() is None

    def test_email_default_si_no_env(self, monkeypatch):
        monkeypatch.setenv("APP_PASSWORD", "super-secreto-12345")
        monkeypatch.delenv("ADMIN_EMAIL", raising=False)
        u = bootstrap_admin_si_falta()
        assert u.email == usuarios.DEFAULT_ADMIN_EMAIL
