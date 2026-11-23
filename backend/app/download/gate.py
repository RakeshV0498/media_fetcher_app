from dataclasses import dataclass


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    reason: str = ""


def check_gate(downloads_enabled: bool, vpn_ok: bool, client_is_mock: bool) -> GateResult:
    """Real clients need DOWNLOADS_ENABLED AND a passing VPN check. Mock never touches the network."""
    if client_is_mock:
        return GateResult(True)
    if not downloads_enabled:
        return GateResult(False, "downloads are disabled (DOWNLOADS_ENABLED=false)")
    if not vpn_ok:
        return GateResult(False, "VPN health check failed for the target node")
    return GateResult(True)
