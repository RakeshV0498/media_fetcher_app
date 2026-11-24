"""Safety checks for the render service: which URLs may be fetched, and when a page is a bot-challenge."""
from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlsplit

_CHALLENGE_TITLES = re.compile(
    r"just a moment|attention required|verify you are human|are you a robot|checking your browser|access denied|"
    r"ddos protection|security check|captcha", re.I)
_CHALLENGE_BODY = re.compile(r"cf-chl|challenge-platform|cf-browser-verification|g-recaptcha|h-captcha|hcaptcha|"
                             r"turnstile|enable javascript and cookies to continue", re.I)


RESOLVE = socket.getaddrinfo  # module-level hook: tests replace this, never socket itself


class UrlRefused(ValueError):
    pass


def _is_private(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    return (a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast or a.is_unspecified
            or (a.version == 4 and a in ipaddress.ip_network("100.64.0.0/10")))  # CGNAT / Tailscale range


def check_url(url: str, allow_private: bool = False, resolve=None) -> str:
    """Return the URL if it is safe to fetch, else raise UrlRefused. Blocks non-http(s), embedded credentials and
    hosts that resolve to loopback / private / link-local addresses (so a scraped link can't reach your LAN)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UrlRefused("only http and https URLs can be rendered")
    if parts.username or parts.password:
        raise UrlRefused("URLs with embedded credentials are not allowed")
    host = parts.hostname
    if not host:
        raise UrlRefused("the URL has no host")
    if allow_private:
        return url
    resolve = resolve or RESOLVE
    try:
        infos = resolve(host, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError as e:
        raise UrlRefused(f"cannot resolve {host}: {e}") from e
    for info in infos:
        ip = info[4][0].split("%")[0]
        if _is_private(ip):
            raise UrlRefused(f"{host} resolves to a private/internal address ({ip}); refusing to fetch it")
    return url


def detect_block(status: int, title: str, html: str) -> str | None:
    """A human-verification / bot-challenge page. We report it instead of trying to get around it."""
    if _CHALLENGE_TITLES.search(title or ""):
        return f'the site is showing a verification page ("{title.strip()[:60]}")'
    if status in (401, 403, 429, 503) and _CHALLENGE_BODY.search(html[:200_000]):
        return f"the site answered HTTP {status} with a bot-check page"
    if status in (403, 429):
        return f"the site refused automated access (HTTP {status})"
    return None
