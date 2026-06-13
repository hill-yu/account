from __future__ import annotations

import requests


class EgressCheckError(RuntimeError):
    pass


class EgressChecker:
    def __init__(
        self,
        *,
        check_url: str,
        proxies: dict[str, str],
        timeout_seconds: int,
        session: requests.Session | None = None,
    ) -> None:
        self._check_url = check_url
        self._proxies = proxies
        self._timeout_seconds = timeout_seconds
        self._session = session or requests.Session()

    def get_observed_ip(self) -> str:
        if self._check_url.startswith("inline://"):
            observed_ip = self._check_url.removeprefix("inline://").strip()
            if not observed_ip:
                raise EgressCheckError("Inline egress check URL did not include an IP value")
            return observed_ip
        response = self._session.get(
            self._check_url,
            proxies=self._proxies,
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        observed_ip = response.text.strip()
        if not observed_ip:
            raise EgressCheckError("Egress IP check returned an empty response")
        return observed_ip
