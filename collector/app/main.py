from __future__ import annotations

from app.config import load_bootstrap_settings
from app.control_plane_client import ControlPlaneClient
from app.runtime import CollectorRuntime


def main() -> int:
    bootstrap_settings = load_bootstrap_settings()
    control_plane_client = ControlPlaneClient(
        base_url=bootstrap_settings.control_plane_base_url,
        instance_token=bootstrap_settings.instance_token,
        timeout_seconds=bootstrap_settings.request_timeout_seconds,
    )
    runtime_config = control_plane_client.get_runtime_config()
    settings = runtime_config.to_runtime_settings(bootstrap_settings.instance_token)
    runtime = CollectorRuntime.from_settings(settings)
    result = runtime.run_once()
    if result.outcome == "blocked":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
