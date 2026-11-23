export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

let onUnauthorized: () => void = () => {};
export const setUnauthorizedHandler = (fn: () => void) => (onUnauthorized = fn);

export async function api<T = unknown>(path: string, method = "GET", body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401 && !path.startsWith("/api/auth/login")) onUnauthorized();
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, msg);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export interface Variant {
  id: number; source_id: number; quality: string | null; codec: string | null;
  size_bytes: number | null; seeders: number | null; leechers: number | null;
  language: string | null; title: string;
}
export interface Release {
  id: number; title: string; year: number | null; season: number | null;
  episode: number | null; absolute_episode: number | null; kind: string; status: string;
  poster_url: string | null; overview: string | null; genres: string[];
  detail_url: string | null; needs_versions: boolean;
  suggested_tag_id: number | null; variant_count: number; variants: Variant[];
}
export interface Tag { id: number; name: string; kind: string; node_id: number | null; qbit_category: string; final_path: string }
export interface Source {
  id: number; name: string; url: string; feed_url: string | null; mode: string;
  selectors: Record<string, string>; user_agent: string; interval_minutes: number;
  cron: string | null; enabled: boolean; default_tag_id: number | null; last_status: string;
}
export interface Download {
  id: number; title: string; season: number | null; episode: number | null; quality: string | null;
  tag: string; node: string; status: string; progress: number; speed: number; eta: number | null; error: string; files: string[];
}
export interface NodeInfo {
  id: number; name: string; agent_url: string; qbit_url: string; download_dir: string; max_concurrent: number;
  vpn_ok: boolean; vpn_required: boolean; vpn: string; public_ip: string | null; home_ip: string | null;
}

export const fmtSize = (b: number | null) =>
  b == null ? "?" : b >= 1e9 ? `${(b / 1e9).toFixed(2)} GB` : `${Math.round(b / 1e6)} MB`;
export const fmtEp = (r: { season: number | null; episode: number | null; absolute_episode: number | null }) =>
  r.season != null && r.episode != null
    ? `S${String(r.season).padStart(2, "0")}E${String(r.episode).padStart(2, "0")}`
    : r.absolute_episode != null ? `Ep ${r.absolute_episode}` : "";

export interface AppField {
  key: string; label: string; group: string; kind: "text" | "url" | "secret" | "bool" | "int" | "float" | "select";
  help: string; options: string[]; danger: boolean; source: "db" | "env";
  value?: string | number | boolean; set?: boolean; unreadable?: boolean;
}
export interface VpnForm {
  provider: string; type: string; countries: string; port_forwarding: boolean; wireguard_addresses: string;
  wireguard_private_key: string; openvpn_user: string; openvpn_password: string;
  wireguard_private_key_set?: boolean; openvpn_password_set?: boolean;
}
export interface BrowseResult { path: string; parent: string | null; dirs: string[]; roots: string[]; absolute: boolean }
