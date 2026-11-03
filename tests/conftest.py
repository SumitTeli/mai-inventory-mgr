import logging
import os
import sys
import tempfile
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Settings for the tests, before the app is imported: a throwaway database
# folder, and the API switched on with a test key.
os.environ["STAGE"] = "dev"
os.environ["MAI_DB_ROOT"] = tempfile.mkdtemp(prefix="mai-tests-") + "/"
os.environ["MAI_API_KEY"] = "test-key"
os.environ["MAI_API_CLIENT_NAME"] = "test-client"

# Tests never send logs to the Loki server: the Loki handler is replaced by one
# that drops every record.
class _NoLokiHandler(logging.Handler):
    def __init__(self, **kwargs):
        super().__init__()

    def emit(self, record):
        pass

sys.modules["logging_loki"] = types.SimpleNamespace(LokiQueueHandler=_NoLokiHandler)

from app import app as flask_app  # noqa: E402
from app.database import db_interface as database  # noqa: E402
from app.database import db_util  # noqa: E402


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A fresh database for every test, plus a few categories."""
    monkeypatch.setattr(db_util, "DATA_DB_PATH", str(tmp_path / "mai.db"))
    monkeypatch.setattr(db_util, "LOG_DB_PATH", str(tmp_path / "mai-log.db"))
    database.init_db()

    database.insert_category("OR Equipment")
    database.insert_category("PPE")
    categories = {c["name"]: c["id"] for c in database.get_all_active_categories()}
    database.insert_subcategory("Surgical/Wound Dressing", categories["OR Equipment"])
    subcategories = {s["name"]: s["id"] for s in database.get_all_active_subcategories_for_category(categories["OR Equipment"])}

    flask_app.config["TESTING"] = True
    return {
        "client": flask_app.test_client(),
        "categories": categories,
        "subcategories": subcategories,
        "db_path": str(tmp_path / "mai.db"),
    }
