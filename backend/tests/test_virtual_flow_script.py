from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT_DIR / "scripts" / "virtual_flow.py"


def _load_virtual_flow_module():
    spec = spec_from_file_location("virtual_flow_script", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_virtual_flow_runner_completes_stub_roundtrip() -> None:
    module = _load_virtual_flow_module()

    summary = module.run_virtual_flow()

    assert summary["collector_exit_code"] == 0
    assert summary["task_status"] == "succeeded"
    assert summary["site_rows"] == 2
    assert summary["first_url"] == "https://stub.example.com/"
    assert summary["responses_served"] == 2000
    assert summary["revenue"] == 22.0
