import { useEffect, useState } from "react";
import { api, NodeInfo, Tag } from "../api";
import type { ToastFn } from "../App";

export function Tags({ notify }: { notify: ToastFn }) {
  const [tags, setTags] = useState<Tag[]>([]);
  const [nodes, setNodes] = useState<NodeInfo[]>([]);
  const [quality, setQuality] = useState("1080p");
  useEffect(() => {
    api<Tag[]>("/api/tags").then(setTags);
    api<NodeInfo[]>("/api/nodes").then(setNodes);
    api<{ preferred_quality: string }>("/api/settings").then((s) => setQuality(s.preferred_quality));
  }, []);
  const patch = (id: number, p: Partial<Tag>) => setTags((l) => l.map((t) => (t.id === id ? { ...t, ...p } : t)));
  const save = (t: Tag) => api(`/api/tags/${t.id}`, "PUT", t).then(() => notify(`Saved ${t.name}`)).catch((e) => notify(e.message, true));

  return (
    <>
      <section className="card row">
        <label>Preferred quality (used by bulk approve)
          <select value={quality} onChange={(e) => { setQuality(e.target.value); api("/api/settings", "PUT", { preferred_quality: e.target.value }); }}>
            {["2160p", "1080p", "720p", "480p"].map((q) => <option key={q}>{q}</option>)}
          </select>
        </label>
      </section>
      {tags.map((t) => (
        <article key={t.id} className="card form">
          <h3>{t.name} <span className="badge">{t.kind}</span></h3>
          <label>Node
            <select value={t.node_id ?? ""} onChange={(e) => patch(t.id, { node_id: e.target.value ? Number(e.target.value) : null })}>
              <option value="">—</option>{nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
            </select>
          </label>
          <label>qBittorrent category<input value={t.qbit_category} onChange={(e) => patch(t.id, { qbit_category: e.target.value })} /></label>
          <label>Final folder (absolute path on that Pi)<input value={t.final_path} onChange={(e) => patch(t.id, { final_path: e.target.value })} /></label>
          <button className="primary" onClick={() => save(t)}>Save</button>
        </article>
      ))}
    </>
  );
}
