import json
from pathlib import Path

import pytest

from app.core.config import load_config
from app.models.alertmanager import AlertmanagerPayload

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config():
    return load_config(str(ROOT / "config" / "config.yaml"))


@pytest.fixture
def firing():
    return AlertmanagerPayload.model_validate(json.loads((ROOT / "tests/fixtures/alert-firing.json").read_text(encoding="utf-8")))
