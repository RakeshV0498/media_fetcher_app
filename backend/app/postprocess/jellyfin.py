import httpx


def refresh_library(base_url: str, api_key: str, client: httpx.Client | None = None) -> bool:
    """POST /Library/Refresh. Returns False (never raises) so a Jellyfin outage can't fail a filing."""
    if not base_url or not api_key:
        return False
    own = client is None
    client = client or httpx.Client(timeout=10)
    try:
        r = client.post(f"{base_url.rstrip('/')}/Library/Refresh", headers={"X-Emby-Token": api_key})
        return r.status_code in (200, 204)
    except httpx.HTTPError:
        return False
    finally:
        if own:
            client.close()
