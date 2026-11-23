import { useEffect, useState } from "react";
import { api, Source } from "../api";
import type { ToastFn } from "../App";

const EMPTY = { name: "", url: "", mode: "auto", interval_minutes: 60, cron: "", user_agent: "", selectors: "{}" };
const SEL_HINT = '{"item":"tr.row","title":"a.title","link":"a.title@href","magnet":"a.magnet@href","size":".size","seeders":".seeds","leechers":".leech","date":".date"}';

export function Sources({ notify }: { notify: ToastFn }) {
  const [list, setList] = useState<Source[]>([]);
  const [form, setForm] = useState(EMPTY);
  const [editing, setEditing] = useState<number | null>(null);
  const load = () => api<Source[]>("/api/sources").then(setList);
  useEffect(() => { load(); }, []);

  const save = async () => {
    let selectors: Record<string, string>;
    try { selectors = JSON.parse(form.selectors || "{}"); } catch { return notify("Selectors must be valid JSON", true); }
    const body = { ...form, selectors, cron: form.cron || null };
    try {
      await api(editing ? `/api/sources/${editing}` : "/api/sources", editing ? "PUT" : "POST", body);
      setForm(EMPTY); setEditing(null); load(); notify("Saved");
    } catch (e) { notify((e as Error).message, true); }
  };

  return (
    <>
      <section className="card form">
        <h3>{editing ? "Edit source" : "Add source"}</h3>
        <label>Name<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label>Site URL<input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} /></label>
        <label>Mode
          <select value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })}>
            <option value="auto">auto (feed, else HTML)</option><option value="feed">feed only</option><option value="html">HTML only</option>
          </select>
        </label>
        <label>Every (minutes)<input type="number" min={1} value={form.interval_minutes} onChange={(e) => setForm({ ...form, interval_minutes: Number(e.target.value) })} /></label>
        <label>…or cron (overrides interval)<input placeholder="*/30 * * * *" value={form.cron} onChange={(e) => setForm({ ...form, cron: e.target.value })} /></label>
        <label>User-Agent (blank = default)<input value={form.user_agent} onChange={(e) => setForm({ ...form, user_agent: e.target.value })} /></label>
        <label>HTML selectors (JSON)<textarea rows={4} placeholder={SEL_HINT} value={form.selectors} onChange={(e) => setForm({ ...form, selectors: e.target.value })} /></label>
        <div className="row">
          <button className="primary" onClick={save}>{editing ? "Update" : "Add"}</button>
          <button onClick={async () => { try { const r = await api<{ feed_url: string | null }>(`/api/sources/discover?url=${encodeURIComponent(form.url)}`, "POST"); notify(r.feed_url ? `Feed found: ${r.feed_url}` : "No feed found — use HTML selectors", !r.feed_url); } catch (e) { notify((e as Error).message, true); } }}>Discover feed</button>
          {editing && <button onClick={() => { setEditing(null); setForm(EMPTY); }}>Cancel</button>}
        </div>
      </section>
      {list.map((s) => (
        <article key={s.id} className="card">
          <div className="row"><h3>{s.name}</h3><span className="badge">{s.mode}</span><span className="muted">{s.url}</span></div>
          <p className="muted">Feed: {s.feed_url ?? "none"} · {s.cron ?? `every ${s.interval_minutes}m`} · {s.last_status || "never scanned"}</p>
          <div className="row">
            <button onClick={async () => { const r = await api<{ status: string }>(`/api/sources/${s.id}/scan`, "POST"); notify(r.status, r.status.startsWith("error")); load(); }}>Scan now</button>
            <button onClick={() => { setEditing(s.id); setForm({ name: s.name, url: s.url, mode: s.mode, interval_minutes: s.interval_minutes, cron: s.cron ?? "", user_agent: s.user_agent, selectors: JSON.stringify(s.selectors) }); }}>Edit</button>
            <button onClick={async () => { if (confirm(`Delete ${s.name}?`)) { await api(`/api/sources/${s.id}`, "DELETE"); load(); } }}>Delete</button>
          </div>
        </article>
      ))}
    </>
  );
}
