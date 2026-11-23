import { useEffect, useState } from "react";
import { api, NodeInfo, Tag } from "../api";
import type { ToastFn } from "../App";
import { Icon, PageHead } from "../ui";

export function Tags({ notify }: { notify: ToastFn }) {
  const [tags, setTags] = useState<Tag[] | null>(null);
  const [nodes, setNodes] = useState<NodeInfo[]>([]);
  const [quality, setQuality] = useState("1080p");
  useEffect(() => {
    api<Tag[]>("/api/tags").then(setTags);
    api<NodeInfo[]>("/api/nodes").then(setNodes);
    api<{ preferred_quality: string }>("/api/settings").then((s) => setQuality(s.preferred_quality));
  }, []);
  const patch = (id: number, p: Partial<Tag>) => setTags((l) => l && l.map((t) => (t.id === id ? { ...t, ...p } : t)));
  const save = (t: Tag) => api(`/api/tags/${t.id}`, "PUT", t).then(() => notify(`Saved ${t.name}`)).catch((e) => notify(e.message, true));
  const setQ = (q: string) => { setQuality(q); api("/api/settings", "PUT", { preferred_quality: q }).then(() => notify(`Preferred quality: ${q}`)); };

  return (
    <>
      <PageHead title="Tags & libraries" sub="Each tag sends downloads to a node and files them into a library folder on that Pi." />
      <section className="card pref">
        <div><h3>Preferred quality</h3><p className="sub">Used by “Approve preferred” and the Telegram ordering tie-break.</p></div>
        <div className="segmented">{["2160p", "1080p", "720p", "480p"].map((q) => <button key={q} className={quality === q ? "on" : ""} onClick={() => setQ(q)}>{q}</button>)}</div>
      </section>
      <div className="grid forms">
        {tags?.map((t) => (
          <article key={t.id} className="card form-card">
            <div className="title-row"><h3>{t.name}</h3><span className={`chip kind-${t.kind}`}>{t.kind}</span></div>
            <label className="field">Node
              <select value={t.node_id ?? ""} onChange={(e) => patch(t.id, { node_id: e.target.value ? Number(e.target.value) : null })}>
                <option value="">— none —</option>{nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
              </select></label>
            <label className="field">qBittorrent category<input value={t.qbit_category} onChange={(e) => patch(t.id, { qbit_category: e.target.value })} /></label>
            <label className="field">Final folder <span className="hint">absolute path on that Pi</span><input className="mono" value={t.final_path} onChange={(e) => patch(t.id, { final_path: e.target.value })} /></label>
            <div className="form-actions"><button className="btn primary" onClick={() => save(t)}><Icon name="check" size={16} />Save</button></div>
          </article>
        ))}
      </div>
    </>
  );
}
