"""
Configuración compartida de pytest.

- DATA_DIR se setea a un directorio temporal por sesión de tests para no
  contaminar el historial real ni los códigos de verificación.
- SENTRY_DSN se vacía para no enviar tests a Sentry de producción.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

# IMPORTANTE: estos env vars DEBEN setearse ANTES de importar src.*
_TMPDIR = tempfile.mkdtemp(prefix="jr-verifica-tests-")
os.environ["DATA_DIR"]          = _TMPDIR
os.environ["SENTRY_DSN"]        = ""           # desactivar Sentry en tests
os.environ["SCHEDULER_ENABLED"] = "0"          # no arrancar APScheduler
os.environ["CACHE_TTL_SEG"]     = "300"        # TTL corto para tests determinísticos

# Asegurar que `src` esté en el path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def _limpiar_historial_entre_tests():
    """
    Cada test arranca con la DB vacía para evitar contaminación cruzada.
    """
    from src.historial_sqlite import limpiar_todo
    limpiar_todo()
    yield
    # post-test cleanup también
    try:
        limpiar_todo()
    except Exception:
        pass
