from dataclasses import dataclass


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    reason: str = ""


def vpn_healthy(vpn_running: bool, vpn_ip: str | None, home_ip: str | None) -> GateResult:
    """VPN passes only if the tunnel is up AND its public IP is known and differs from the home IP.
    Any unknown (no IP, home IP unknown) fails closed."""
    if not vpn_running:
        return GateResult(False, "VPN health check failed: tunnel is not connected")
    if not vpn_ip:
        return GateResult(False, "VPN health check failed: VPN public IP unknown")
    if not home_ip:
        return GateResult(False, "VPN health check failed: home public IP unknown (cannot compare)")
    if vpn_ip == home_ip:
        return GateResult(False, "VPN health check failed: public IP equals home IP (traffic not protected)")
    return GateResult(True)


def enough_space(free_bytes: int, needed_bytes: int | None, reserve_bytes: int = 5 * 1024**3) -> GateResult:
    need = int((needed_bytes or 0) * 1.1) + reserve_bytes
    if free_bytes < need:
        return GateResult(False, f"not enough disk space: {free_bytes / 1e9:.1f} GB free, need {need / 1e9:.1f} GB")
    return GateResult(True)


def check_gate(downloads_enabled: bool, vpn: GateResult | bool, client_is_mock: bool) -> GateResult:
    """Real clients need DOWNLOADS_ENABLED AND a passing VPN check. Mock never touches the network."""
    if client_is_mock:
        return GateResult(True)
    if not downloads_enabled:
        return GateResult(False, "downloads are disabled (DOWNLOADS_ENABLED=false)")
    if isinstance(vpn, bool):
        vpn = GateResult(vpn, "" if vpn else "VPN health check failed for the target node")
    return vpn if not vpn.allowed else GateResult(True)
