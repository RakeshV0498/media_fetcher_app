from __future__ import annotations

import re
import time
import uuid

import httpx

from .client import Progress

_DOWN = {"downloading", "stalledDL", "metaDL", "forcedMetaDL", "queuedDL", "forcedDL",
         "allocating", "checkingDL", "checkingResumeData", "moving"}
_PAUSED = {"pausedDL", "stoppedDL"}
_DONE = {"uploading", "stalledUP", "pausedUP", "stoppedUP", "queuedUP", "forcedUP", "checkingUP"}
_FAILED = {"error", "missingFiles"}
TAG_PREFIX = "mf-"


class QBittorrentClient:
    """qBittorrent Web API v2. client_id is a unique tag we put on the torrent (hash-free)."""
    is_mock = False

    def __init__(self, base_url: str, username: str, password: str,
                 http: httpx.Client | None = None, max_active: int | None = None,
                 confirm_seconds: float = 15.0, sleep=time.sleep) -> None:
        self.base = base_url.rstrip("/")
        self.user, self.pw = username, password
        self.http = http or httpx.Client(timeout=15)
        self._logged_in = False
        self.max_active = max_active
        self.confirm_seconds, self._sleep = confirm_seconds, sleep

    # -- plumbing
    def _login(self) -> None:
        r = self.http.post(f"{self.base}/api/v2/auth/login", data={"username": self.user, "password": self.pw},
                           headers={"Referer": self.base})
        if r.status_code == 403 and "banned" in r.text.lower():
            raise RuntimeError("qBittorrent has temporarily banned this IP after too many failed logins - "
                               "restart the qbittorrent container (docker restart deploy-qbittorrent-1) and try again")
        if r.status_code == 200 and r.text.strip() == "Fails.":
            raise RuntimeError("qBittorrent rejected the username or password (the same login is used for every node)")
        # Success is 200 "Ok." on older qBittorrent and 204 No Content on newer releases.
        if not (r.status_code == 204 or (r.status_code == 200 and r.text.strip() == "Ok.")):
            raise RuntimeError(f"qBittorrent login failed (HTTP {r.status_code}: {r.text.strip()[:80] or 'no body'})")
        self._logged_in = True
        self._configure()

    def _configure(self) -> None:
        """Never seed: ratio limit 0 + pause when reached; queue to the node's concurrency limit."""
        import json
        prefs = {"max_ratio_enabled": True, "max_ratio": 0, "max_ratio_act": 0,
                 "max_seeding_time_enabled": True, "max_seeding_time": 0}
        if self.max_active:
            prefs.update(queueing_enabled=True, max_active_downloads=self.max_active)
        self.http.post(f"{self.base}/api/v2/app/setPreferences", data={"json": json.dumps(prefs)},
                       headers={"Referer": self.base})

    def _req(self, method: str, path: str, **kw) -> httpx.Response:
        if not self._logged_in:
            self._login()
        kw.setdefault("headers", {})["Referer"] = self.base
        r = self.http.request(method, f"{self.base}{path}", **kw)
        if r.status_code == 403:  # session expired
            self._login()
            r = self.http.request(method, f"{self.base}{path}", **kw)
        return r

    def _hash(self, client_id: str) -> str | None:
        info = self._info(client_id)
        return info["hash"] if info else None

    def _info(self, client_id: str) -> dict | None:
        r = self._req("GET", "/api/v2/torrents/info", params={"tag": client_id})
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None

    # -- DownloadClient
    def add(self, uri: str, category: str, save_path: str) -> str:
        tag = f"{TAG_PREFIX}{uuid.uuid4().hex[:12]}"
        r = self._req("POST", "/api/v2/torrents/add", data={
            "urls": uri, "category": category, "savepath": save_path, "tags": tag,
            "ratioLimit": 0, "seedingTimeLimit": 0, "autoTMM": "false"})
        # 200 "Ok." / 204 (older), or 202 with pending_count>0 (qBittorrent 5.x: queued, still fetching metadata).
        if r.status_code not in (200, 202, 204) or "Fails" in r.text:
            raise RuntimeError(f"qBittorrent rejected the torrent ({r.status_code}: {r.text[:100]})")
        try:  # newer versions answer with JSON counts instead of "Ok."
            counts = r.json()
        except ValueError:
            counts = None
        if isinstance(counts, dict) and counts.get("failure_count", 0) and not counts.get("success_count", 0) \
                and not counts.get("pending_count", 0):
            raise RuntimeError("qBittorrent rejected the torrent (is it a duplicate or an invalid link?)")
        self._confirm_listed(tag, uri)
        return tag

    def _add_failure(self, uri: str) -> str | None:
        """qBittorrent logs 'Failed to add torrent ... Reason: "..."' for async URL adds; surface that reason."""
        try:
            r = self._req("GET", "/api/v2/log/main", params={"normal": "false", "info": "false",
                                                              "warning": "true", "critical": "true"})
            entries = r.json() if r.status_code == 200 else []
        except (httpx.HTTPError, ValueError):
            return None
        for e in reversed(entries if isinstance(entries, list) else []):
            msg = str(e.get("message", ""))
            if "Failed to add torrent" in msg and uri in msg:
                m = re.search(r'Reason: "(.*?)"', msg)
                return m.group(1) if m else msg[:160]
        return None

    def _confirm_listed(self, tag: str, uri: str) -> None:
        """qBittorrent 5.x answers 202 'pending' before the torrent exists (and may fail afterwards, e.g. a 404
        .torrent URL). Never record a download that qBittorrent does not actually list."""
        if self.confirm_seconds <= 0:
            return
        waited = 0.0
        while True:
            if self._info(tag) is not None:
                return
            reason = self._add_failure(uri)
            if reason:
                raise RuntimeError(f"qBittorrent could not add it: {reason}. The link may be stale or removed - "
                                   "check it in the source, or pick another version.")
            if waited >= self.confirm_seconds:
                raise RuntimeError(
                    f"qBittorrent accepted the request but the torrent never appeared in its list within "
                    f"{int(self.confirm_seconds)}s (is the link a valid magnet / .torrent, and does it have peers or "
                    "a reachable tracker?)")
            self._sleep(1.0)
            waited += 1.0

    def status(self, client_id: str) -> Progress | None:
        i = self._info(client_id)
        if i is None:
            return None
        state, prog = i.get("state", ""), float(i.get("progress", 0))
        if state in _FAILED:
            kind = "failed"
        elif state in _PAUSED and prog < 1:
            kind = "paused"
        elif prog >= 1 or state in _DONE:
            kind = "done"
        else:
            kind = "downloading"
        eta = i.get("eta")
        return Progress(client_id, kind, prog, int(i.get("dlspeed", 0)),
                        None if eta in (None, 8640000) else int(eta), i.get("content_path"))

    def _act(self, client_id: str, new: str, old: str) -> None:
        h = self._hash(client_id)
        if not h:
            return
        r = self._req("POST", f"/api/v2/torrents/{new}", data={"hashes": h})
        if r.status_code == 404:  # qBittorrent < 5 uses pause/resume
            self._req("POST", f"/api/v2/torrents/{old}", data={"hashes": h}).raise_for_status()

    def pause(self, client_id: str) -> None:
        self._act(client_id, "stop", "pause")

    def resume(self, client_id: str) -> None:
        self._act(client_id, "start", "resume")

    def remove(self, client_id: str, delete_files: bool = False) -> None:
        h = self._hash(client_id)
        if h:
            self._req("POST", "/api/v2/torrents/delete",
                      data={"hashes": h, "deleteFiles": "true" if delete_files else "false"}).raise_for_status()
