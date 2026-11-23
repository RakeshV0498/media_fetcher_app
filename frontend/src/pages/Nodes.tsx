import { useEffect, useState } from "react";
import { api, NodeInfo } from "../api";

export function Nodes(_: { notify: unknown }) {
  const [nodes, setNodes] = useState<NodeInfo[]>([]);
  useEffect(() => { api<NodeInfo[]>("/api/nodes").then(setNodes); }, []);
  return (
    <>
      {nodes.map((n) => (
        <article key={n.id} className="card">
          <h3>{n.name}</h3>
          <p className="muted">VPN: {n.vpn} · Public IP: {n.public_ip ?? "–"} · Agent: {n.agent_url || "not set"}</p>
        </article>
      ))}
    </>
  );
}
