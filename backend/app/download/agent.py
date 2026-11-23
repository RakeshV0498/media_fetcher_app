"""Controller-side client for a node agent (runs beside gluetun + qBittorrent on each Pi)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from ..config import settings
from ..postprocess.mover import MoveResult, NeedsAttention, PathNotAllowed
from .gate import GateResult, vpn_healthy


@dataclass
class VpnInfo:
    gate: GateResult
    running: bool = False
    vpn_ip: str | None = None
    home_ip: str | None = None


class AgentError(Exception):
    pass


class AgentClient:
    def __init__(self, base_url: str, token: str | None = None, http: httpx.Client | None = None) -> None:
        self.base = base_url.rstrip("/")
        self.http = http or httpx.Client(timeout=20)
        self.headers = {"Authorization": f"Bearer {token if token is not None else settings.node_agent_token}"}

    def _call(self, method: str, path: str, **kw) -> httpx.Response:
        try:
            return self.http.request(method, f"{self.base}{path}", headers=self.headers, **kw)
        except httpx.HTTPError as e:
            raise AgentError(f"node agent unreachable: {e}") from e

    def vpn(self, home_ip_override: str = "") -> VpnInfo:
        """Fail closed on any error."""
        try:
            r = self._call("GET", "/vpn")
            if r.status_code != 200:
                return VpnInfo(GateResult(False, f"VPN health check failed: agent returned {r.status_code}"))
            d = r.json()
        except (AgentError, ValueError) as e:
            return VpnInfo(GateResult(False, f"VPN health check failed: {e}"))
        home = home_ip_override or d.get("home_ip")
        running = d.get("vpn_status") == "running"
        return VpnInfo(vpn_healthy(running, d.get("vpn_ip"), home), running, d.get("vpn_ip"), home)

    def free_bytes(self, path: str) -> int:
        r = self._call("GET", "/disk", params={"path": path})
        if r.status_code != 200:
            raise AgentError(f"disk check failed ({r.status_code}: {r.text[:100]})")
        return int(r.json()["free_bytes"])

    def postprocess(self, content_path: str, root: str, kind: str, title: str, year: int | None,
                    season: int | None, episode: int | None) -> MoveResult:
        r = self._call("POST", "/postprocess", json={
            "content_path": content_path, "root": root, "kind": kind, "title": title,
            "year": year, "season": season, "episode": episode})
        if r.status_code == 422:
            raise NeedsAttention(r.json()["detail"])
        if r.status_code == 403:
            raise PathNotAllowed(r.json()["detail"])
        if r.status_code == 404:
            raise FileNotFoundError(r.json()["detail"])
        if r.status_code != 200:
            raise OSError(f"node agent error {r.status_code}: {r.text[:200]}")
        d = r.json()
        return MoveResult(moved=[(Path(a), Path(b)) for a, b in d["moved"]],
                          duplicates=[Path(p) for p in d["duplicates"]],
                          skipped=[Path(p) for p in d["skipped"]])

    # ---- folder browsing (limited by the agent to its MEDIA_ROOTS) ----
    def browse(self, path: str = "") -> dict:
        r = self._call("GET", "/browse", params={"path": path})
        if r.status_code != 200:
            raise AgentError(r.json().get("detail", f"browse failed ({r.status_code})") if r.headers.get(
                "content-type", "").startswith("application/json") else f"browse failed ({r.status_code})")
        return r.json()

    def mkdir(self, path: str) -> dict:
        r = self._call("POST", "/mkdir", json={"path": path})
        if r.status_code != 200:
            raise AgentError(r.json().get("detail", f"mkdir failed ({r.status_code})"))
        return r.json()

    # ---- VPN provider settings (pushed to gluetun by the agent) ----
    def vpn_settings_get(self) -> dict:
        r = self._call("GET", "/vpn/settings")
        if r.status_code != 200:
            raise AgentError(r.json().get("detail", f"agent returned {r.status_code}"))
        return r.json()

    def vpn_settings_apply(self, values: dict) -> dict:
        r = self._call("PUT", "/vpn/settings", json=values)
        if r.status_code != 200:
            raise AgentError(r.json().get("detail", f"agent returned {r.status_code}"))
        return r.json()
