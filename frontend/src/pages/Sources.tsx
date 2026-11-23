import { useEffect, useState } from "react";
import { api, Source } from "../api";
import type { ToastFn } from "../App";
import { Empty, Icon, PageHead } from "../ui";

const EMPTY = { name: "", url: "", mode: "auto", interval_minutes: 60, cron: "", user_agent: "", selectors: "{}" };
const SEL_EXAMPLE = '{\n  "item": "tr.row",\n  "title": "a.title",\n  "link": "a.title@href",\n  "magnet": "a.magnet@href",\n  "size": ".size",\n  "seeders": ".seeds",\n  "leechers": ".leech"\n}';
const SEL_TWO_LEVEL = '{\n  "item": "div.entry",\n  "title": "a.title",\n  "link": "a.title@href",\n  "detail": {\n    "item": "div.version",\n    "title": ".name",\n    "magnet": "a.magnet@href",\n    "torrent": "a.torrent@href",\n    "size": ".size",\n    "seeders": ".seeds"\n  }\n}';
const MODES: Record<string, string> = { auto: "Auto (feed, else HTML)", feed: "Feed only", html: "HTML only" };

export function Sources({ notify }: { notify: ToastFn }) {
  const [list, setList] = useState<Source[] | null>(null);
  const [form, setForm] = useState(EMPTY);
  const [editing, setEditing] = useState<number | null>(null);
  const [open, setOpen] = useState(false);
  const [scanning, setScanning] = useState<number | null>(null);
  const load = () => api<Source[]>("/api/sources").then(setList);
  useEffect(() => { load(); }, []);
  const set = (p: Partial<typeof EMPTY>) => setForm((f) => ({ ...f, ...p }));

  const save = async () => {
    let selectors: Record<string, string>;
    try { selectors = JSON.parse(form.selectors || "{}"); } catch { return notify("Selectors must be valid JSON", true); }
    try {
      await api(editing ? `/api/sources/${editing}` : "/api/sources", editing ? "PUT" : "POST", { ...form, selectors, cron: form.cron || null });
      setForm(EMPTY); setEditing(null); setOpen(false); load(); notify("Source saved");
    } catch (e) { notify((e as Error).message, true); }
  };
  const discover = async () => {
    try {
      const r = await api<{ feed_url: string | null }>(`/api/sources/discover?url=${encodeURIComponent(form.url)}`, "POST");
      notify(r.feed_url ? `Feed found: ${r.feed_url}` : "No feed found — use HTML selectors", !r.feed_url);
    } catch (e) { notify((e as Error).message, true); }
  };
  const startEdit = (s: Source, mode?: string) => {
    setEditing(s.id); setOpen(true);
    setForm({ name: s.name, url: s.url, mode: mode ?? s.mode, interval_minutes: s.interval_minutes, cron: s.cron ?? "", user_agent: s.user_agent,
      selectors: Object.keys(s.selectors).length ? JSON.stringify(s.selectors, null, 2) : "{}" });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const scan = async (id: number) => {
    setScanning(id);
    try { const r = await api<{ status: string }>(`/api/sources/${id}/scan`, "POST"); notify(r.status, r.status.startsWith("error")); load(); }
    catch (e) { notify((e as Error).message, true); } finally { setScanning(null); }
  };

  return (
    <>
      <PageHead title="Sources" sub="Websites to watch. Feeds are used automatically when found; otherwise add CSS selectors.">
        <button className="btn primary" onClick={() => { setEditing(null); setForm(EMPTY); setOpen(!open); }}><Icon name="plus" size={16} />Add source</button>
      </PageHead>

      {open && (
        <section className="card form-card">
          <h3>{editing ? "Edit source" : "New source"}</h3>
          <div className="form-grid">
            <label className="field">Name<input value={form.name} onChange={(e) => set({ name: e.target.value })} placeholder="My tracker" /></label>
            <label className="field">Site URL<input value={form.url} onChange={(e) => set({ url: e.target.value })} placeholder="https://example.org/" /></label>
            <label className="field">Mode<select value={form.mode} onChange={(e) => set({ mode: e.target.value })}>{Object.entries(MODES).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
            <label className="field">Scan every (minutes)<input type="number" min={1} value={form.interval_minutes} onChange={(e) => set({ interval_minutes: Number(e.target.value) })} /></label>
            <label className="field">Cron <span className="hint">overrides interval</span><input className="mono" placeholder="*/30 * * * *" value={form.cron} onChange={(e) => set({ cron: e.target.value })} /></label>
            <label className="field">User-Agent <span className="hint">blank = default</span><input value={form.user_agent} onChange={(e) => set({ user_agent: e.target.value })} /></label>
            <label className="field wide">HTML selectors (JSON) <button type="button" className="link inline" onClick={() => set({ selectors: SEL_EXAMPLE })}>Insert example</button>
              <button type="button" className="link inline" onClick={() => set({ selectors: SEL_TWO_LEVEL })}>Insert two-level example</button>
              <span className="hint">Needs <span className="mono">item</span> and <span className="mono">title</span>. Optional: link, torrent, magnet, size, seeders, leechers, date, <span className="mono">title_regex</span> (keeps the first group of the match as the title). For sites where each title has its own page with the versions, add a <span className="mono">detail</span> block (same keys) and a <span className="mono">link</span> to the page.</span>
              <textarea className="mono" rows={7} value={form.selectors} onChange={(e) => set({ selectors: e.target.value })} spellCheck={false} /></label>
          </div>
          <div className="form-actions">
            <button className="btn primary" onClick={save}>{editing ? "Update source" : "Add source"}</button>
            <button className="btn" onClick={discover} disabled={!form.url}><Icon name="search" size={16} />Discover feed</button>
            <button className="btn ghost" onClick={() => { setOpen(false); setEditing(null); }}>Cancel</button>
          </div>
        </section>
      )}

      {list === null ? <div className="card skeleton" /> : list.length === 0 && !open ? (
        <Empty icon="rss" title="No sources yet" hint="Add a website you're entitled to fetch from to start finding releases." />
      ) : (
        <div className="stack">
          {list.map((s) => {
            const bad = s.last_status.startsWith("error");
            const needsSelectors = bad && /no feed was found/i.test(s.last_status);
            return (
              <article key={s.id} className="card source">
                <div className="source-main">
                  <div className="title-row"><span className={`dot ${!s.last_status ? "muted" : bad ? "bad" : "good"}`} /><h3>{s.name}</h3><span className="chip ghost">{MODES[s.mode] ?? s.mode}</span></div>
                  <p className="url mono">{s.url}</p>
                  {needsSelectors && (
                    <div className="note warn-note"><Icon name="alert" size={16} /><span>No feed was found for this site, so it can only be read from its HTML. Add the CSS selectors that point at each entry and its title.</span>
                      <button className="btn sm" onClick={() => startEdit(s, "html")}><Icon name="pencil" size={14} />Add selectors</button></div>
                  )}
                  <p className="sub">{s.feed_url ? <>Feed: <span className="mono">{s.feed_url}</span> · </> : ""}{s.cron ? <span className="mono">{s.cron}</span> : `every ${s.interval_minutes} min`} · <span className={bad && !needsSelectors ? "text-bad" : ""}>{needsSelectors ? "needs selectors" : s.last_status || "never scanned"}</span></p>
                </div>
                <div className="source-actions">
                  <button className="btn" onClick={() => scan(s.id)} disabled={scanning === s.id}><Icon name="refresh" size={16} />{scanning === s.id ? "Scanning…" : "Scan now"}</button>
                  <button className="btn ghost" onClick={() => startEdit(s)}><Icon name="pencil" size={16} />Edit</button>
                  <button className="btn ghost danger" onClick={async () => { if (confirm(`Delete ${s.name}?`)) { await api(`/api/sources/${s.id}`, "DELETE"); load(); } }}><Icon name="trash" size={16} /></button>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </>
  );
}
