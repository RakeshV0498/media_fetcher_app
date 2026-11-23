import { useCallback, useEffect, useState } from "react";
import { api, NodeInfo } from "../api";
import type { ToastFn } from "../App";
import { Icon, PageHead } from "../ui";

export function Nodes({ notify }: { notify: ToastFn }) {
  const [nodes, setNodes] = useState<NodeInfo[] | null>(null);
  const [off, setOff] = useState(false);
  const load = useCallback(() => {
    api<NodeInfo[]>("/api/nodes").then(setNodes).catch((e) => notify(e.message, true));
    api<{ downloads_enabled: boolean; download_client: string }>("/api/settings")
      .then((s) => setOff(!s.downloads_enabled && s.download_client !== "mock"));
  }, [notify]);
  useEffect(() => { load(); const id = setInterval(load, 15000); return () => clearInterval(id); }, [load]);
  const patch = (id: number, p: Partial<NodeInfo>) => setNodes((l) => l && l.map((n) => (n.id === id ? { ...n, ...p } : n)));
  const save = (n: NodeInfo) =>
    api("/api/nodes/" + n.id, "PUT", { agent_url: n.agent_url, qbit_url: n.qbit_url, max_concurrent: n.max_concurrent })
      .then(() => { notify(`Saved ${n.name}`); load(); }).catch((e) => notify(e.message, true));

  return (
    <>
      <PageHead title="Nodes" sub="One download node per Pi. Downloads only run when the VPN is verified.">
        <button className="btn" onClick={load}><Icon name="refresh" size={16} />Re-check</button>
      </PageHead>
      {off && <div className="banner warn"><Icon name="alert" />Downloads are disabled (DOWNLOADS_ENABLED=false). Approvals are refused until the VPN is verified and the flag is turned on.</div>}
      <div className="grid forms">
        {nodes?.map((n) => (
          <article key={n.id} className="card form-card">
            <div className="title-row">
              <span className={`shield ${n.vpn_ok ? "good" : "bad"}`}><Icon name="shield" size={20} /></span>
              <h3>{n.name}</h3>
              <span className={`status ${n.vpn_ok ? "good" : "bad"}`}><i />{n.vpn_ok ? "VPN protected" : "VPN not verified"}</span>
            </div>
            {!n.vpn_ok && <p className="note bad"><Icon name="alert" size={16} />{n.vpn}</p>}
            <dl className="kv">
              <div><dt>VPN IP</dt><dd className="mono">{n.public_ip ?? "–"}</dd></div>
              <div><dt>Home IP</dt><dd className="mono">{n.home_ip ?? "–"}</dd></div>
            </dl>
            <label className="field">Node agent URL<input className="mono" value={n.agent_url} placeholder="http://pi4.lan:8800" onChange={(e) => patch(n.id, { agent_url: e.target.value })} /></label>
            <label className="field">qBittorrent WebUI URL<input className="mono" value={n.qbit_url} placeholder="http://pi4.lan:8080" onChange={(e) => patch(n.id, { qbit_url: e.target.value })} /></label>
            <label className="field">Max concurrent downloads<input type="number" min={1} value={n.max_concurrent} onChange={(e) => patch(n.id, { max_concurrent: Number(e.target.value) })} /></label>
            <div className="form-actions"><button className="btn primary" onClick={() => save(n)}><Icon name="check" size={16} />Save</button></div>
          </article>
        ))}
      </div>
    </>
  );
}
