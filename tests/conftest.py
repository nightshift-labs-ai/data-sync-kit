import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mock.servers import CRM_TOKEN, SHEET_KEY, MockServer  # noqa: E402
from sync.engine import load_config  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CRM_TOKEN", CRM_TOKEN)
    monkeypatch.setenv("SHEET_KEY", SHEET_KEY)
    crm, sheet = MockServer("crm").start(), MockServer("sheet").start()
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    cfg["source"]["base_url"], cfg["target"]["base_url"] = crm.url, sheet.url
    cfg["retry"]["base_delay"] = 0.01
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    yield {"crm": crm, "sheet": sheet, "cfg": load_config(path), "path": path, "tmp": tmp_path}
    crm.stop()
    sheet.stop()
