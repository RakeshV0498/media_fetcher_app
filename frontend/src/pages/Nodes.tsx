import { useCallback, useEffect, useState } from "react";
import { api, NodeInfo } from "../api";
import type { ToastFn } from "../App";

export function Nodes({ notify }: { notify: ToastFn }) {
  const [nodes, setNodes] = useState<NodeInfo[]>([]);
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const load = useCallback(() => {
    api<NodeInfo[]>("/api/nodes").then(setNodes).catch((e) => notify(e.message, true));
    api<{ downloads_enabled: boolean; download_client: string }>("/api/settings")
      .then((s) => setEnabled(s.downloads_enabled || s.download_client === "mock"));
  }, [notify]);
  useEffect(() => { load(); const id = setInterval(load, 15000); return () => clearInterval(id); }, [load]);
  const patch = (id: number, p: Partial<NodeInfo>) => setNodes((l) => l.map((n) => (n.id === id ? { ...n, ...p } : n)));
  const save = (n: NodeInfo) =>
    api("/api/nodes/" + n.id, "PUT", { agent_url: n.agent_url, qbit_url: n.qbit_url, max_concurrent: n.max_concurrent })
      .then(() => { notify(`Saved ${n.name}`); load(); }).catch((e) => notify(e.message, true));

  return (
    <>
      {enabled === false && <p className="card err">Downloads are disabled (DOWNLOADS_ENABLED=false). Approvals are refused until the VPN is verified and the flag is turned on.</p>}
      {nodes.map((n) => (
        <article key={n.id} className="card form">
          <div className="row">
            <h3>{n.name}</h3>
            <span className={`badge ${n.vpn_ok ? "st-done" : "st-failed"}`}>{n.vpn_ok ? "VPN protected" : "VPN not verified"}</span>
          </div>
          <p className="muted">{n.vpn_ok ? "" : n.vpn + " · "}VPN IP: {n.public_ip ?? "–"} · Home IP: {n.home_ip ?? "–"}</p>
          <label>Node agent URL<input value={n.agent_url} placeholder="http://pi4.lan:8800" onChange={(e) => patch(n.id, { agent_url: e.target.value })} /></label>
          <label>qBittorrent WebUI URL<input value={n.qbit_url} placeholder="http://pi4.lan:8080" onChange={(e) => patch(n.id, { qbit_url: e.target.value })} /></label>
          <label>Max concurrent downloads<input type="number" min={1} value={n.max_concurrent} onChange={(e) => patch(n.id, { max_concurrent: Number(e.target.value) })} /></label>
          <div className="row"><button className="primary" onClick={() => save(n)}>Save</button><button onClick={load}>Re-check</button></div>
        </article>
      ))}
    </>
  );
}
