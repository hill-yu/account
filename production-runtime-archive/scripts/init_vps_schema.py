from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_ROOT = ROOT / "collector"
if str(COLLECTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(COLLECTOR_ROOT))

from app import vps_models  # noqa: F401
from app.vps_database import VpsBase, get_engine


def main() -> int:
    VpsBase.metadata.create_all(bind=get_engine())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
