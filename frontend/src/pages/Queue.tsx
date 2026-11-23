import { useCallback, useEffect, useMemo, useState } from "react";
import { api, fmtEp, fmtSize, Release, Source, Tag } from "../api";
import type { ToastFn } from "../App";
import { Empty, Icon, PageHead, Poster, qualityClass, Skeletons } from "../ui";

const STATUSES = [["new", "New"], ["snoozed", "Snoozed"], ["approved", "Approved"], ["rejected", "Rejected"]] as const;

function Seeders({ n, max }: { n: number | null; max: number }) {
  if (n == null) return <span className="seeders muted">–</span>;
  const pct = max > 0 ? Math.max(6, Math.round((n / max) * 100)) : 6;
  const tone = n === 0 ? "bad" : n < 20 ? "warn" : "good";
  return (
    <span className="seeders" title={`${n} seeders`}>
      <span className="bar"><span className={`fill ${tone}`} style={{ width: `${pct}%` }} /></span>
      <span className="num">{n}</span>
    </span>
  );
}

function Card({ r, tags, sources, selected, onSelect, notify, reload }: {
  r: Release; tags: Tag[]; sources: Source[]; selected: boolean;
  onSelect: (on: boolean) => void; notify: ToastFn; reload: () => void;
}) {
  const [variantId, setVariantId] = useState<number | null>(null);
  const [tagId, setTagId] = useState<number | null>(r.suggested_tag_id);
  const [all, setAll] = useState<Release | null>(null);
  const [busy, setBusy] = useState(false);
  const shown = (all ?? r).variants;
  const maxSeeds = useMemo(() => Math.max(0, ...shown.map((v) => v.seeders ?? 0)), [shown]);
  const srcName = (id: number) => sources.find((s) => s.id === id)?.name ?? `#${id}`;
  const actionable = r.status === "new" || r.status === "snoozed";

  const act = async (path: string, body?: unknown, ok = "Done") => {
    setBusy(true);
    try {
      await api(`/api/releases/${r.id}/${path}`, "POST", body ?? {});
      notify(ok);
      reload();
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className={`card release ${selected ? "selected" : ""}`}>
      <div className="release-top">
        <Poster url={r.poster_url} title={r.title} />
        <div className="release-info">
          <div className="title-row">
            {r.status === "new" && <input type="checkbox" className="check" checked={selected} onChange={(e) => onSelect(e.target.checked)} aria-label={`Select ${r.title}`} />}
            <h3>{r.title}{r.year ? <span className="year"> ({r.year})</span> : null}</h3>
          </div>
          <div className="chips">
            <span className={`chip kind-${r.kind}`}>{r.kind === "movie" ? "Movie" : "Episode"}</span>
            {fmtEp(r) && <span className="chip mono">{fmtEp(r)}</span>}
            {r.genres.slice(0, 3).map((g) => <span key={g} className="chip ghost">{g}</span>)}
          </div>
          {r.overview ? <p className="overview">{r.overview}</p> : <p className="overview muted">No description yet.</p>}
        </div>
      </div>

      <div className="variants" role="radiogroup" aria-label="Choose a version">
        {shown.map((v, i) => (
          <label key={v.id} className={`variant ${variantId === v.id ? "picked" : ""}`}>
            <input type="radio" name={`v${r.id}`} checked={variantId === v.id} onChange={() => setVariantId(v.id)} />
            <span className="radio" aria-hidden="true" />
            <span className={`q ${qualityClass(v.quality)}`}>{v.quality ?? "?"}</span>
            <span className="size">{fmtSize(v.size_bytes)}</span>
            <Seeders n={v.seeders} max={maxSeeds} />
            <span className="meta">{[v.codec, v.language].filter(Boolean).join(" · ") || srcName(v.source_id)}</span>
            {i === 0 && v.seeders != null && <span className="best">Most seeded</span>}
          </label>
        ))}
        {r.variant_count > shown.length && (
          <button className="link" onClick={() => api<Release[]>(`/api/releases?status=${r.status}&all_variants=true`).then((l) => setAll(l.find((x) => x.id === r.id) ?? null))}>
            Show all {r.variant_count} versions
          </button>
        )}
      </div>

      {actionable && (
        <div className="release-actions">
          <div className="select-wrap">
            <select value={tagId ?? ""} onChange={(e) => setTagId(e.target.value ? Number(e.target.value) : null)} aria-label="Library tag">
              <option value="">Select library…</option>
              {tags.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
            <Icon name="chevron" size={16} />
          </div>
          <span className="spacer" />
          <button className="btn ghost" disabled={busy} onClick={() => act("snooze", { hours: 24 }, "Snoozed for 24 hours")} title="Hide for 24 hours"><Icon name="clock" size={16} />Snooze</button>
          <button className="btn ghost danger" disabled={busy} onClick={() => act("reject", undefined, "Rejected")}><Icon name="x" size={16} />Reject</button>
          <button className="btn primary" disabled={busy || variantId == null || tagId == null}
            title={variantId == null ? "Pick a version first" : tagId == null ? "Pick a library first" : ""}
            onClick={() => act("approve", { variant_id: variantId, tag_id: tagId }, "Approved")}><Icon name="check" size={16} />Approve</button>
        </div>
      )}
    </article>
  );
}

export function Queue({ notify }: { notify: ToastFn }) {
  const [releases, setReleases] = useState<Release[] | null>(null);
  const [tags, setTags] = useState<Tag[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [status, setStatus] = useState("new");
  const [tagF, setTagF] = useState("");
  const [srcF, setSrcF] = useState("");
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<Set<number>>(new Set());

  const load = useCallback(() => {
    const p = new URLSearchParams({ status });
    if (tagF) p.set("tag_id", tagF);
    if (srcF) p.set("source_id", srcF);
    if (q) p.set("q", q);
    api<Release[]>(`/api/releases?${p}`).then(setReleases).catch((e) => notify(e.message, true));
    setSel(new Set());
  }, [status, tagF, srcF, q, notify]);

  useEffect(() => { api<Tag[]>("/api/tags").then(setTags); api<Source[]>("/api/sources").then(setSources); }, []);
  useEffect(load, [load]);

  const bulk = async (action: string) => {
    try {
      const r = await api<{ done: number[]; skipped: Record<string, string> }>("/api/releases/bulk", "POST", { ids: [...sel], action });
      const sk = Object.keys(r.skipped).length;
      notify(`${r.done.length} done${sk ? ` · ${sk} skipped (${Object.values(r.skipped)[0]})` : ""}`, sk > 0);
      load();
    } catch (e) { notify((e as Error).message, true); }
  };

  const allIds = releases?.map((r) => r.id) ?? [];
  return (
    <>
      <PageHead title="Review" sub="New releases found by your sources. Pick a version and a library, then approve.">
        <button className="btn" onClick={load}><Icon name="refresh" size={16} />Refresh</button>
      </PageHead>

      <div className="toolbar">
        <div className="segmented" role="tablist">
          {STATUSES.map(([v, label]) => (
            <button key={v} role="tab" aria-selected={status === v} className={status === v ? "on" : ""} onClick={() => setStatus(v)}>{label}</button>
          ))}
        </div>
        <div className="search"><Icon name="search" size={16} /><input placeholder="Search titles…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <div className="select-wrap"><select value={tagF} onChange={(e) => setTagF(e.target.value)} aria-label="Filter by tag"><option value="">All libraries</option>{tags.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select><Icon name="chevron" size={16} /></div>
        <div className="select-wrap"><select value={srcF} onChange={(e) => setSrcF(e.target.value)} aria-label="Filter by source"><option value="">All sources</option>{sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select><Icon name="chevron" size={16} /></div>
      </div>

      {releases === null ? <Skeletons /> : releases.length === 0 ? (
        <Empty icon="inbox" title={status === "new" ? "You're all caught up" : `Nothing ${status}`}
          hint={status === "new" ? "New releases appear here after a source scan. Add sources and press Scan now." : undefined} />
      ) : (
        <div className="grid">
          {releases.map((r) => (
            <Card key={`${r.id}-${r.variants.length}`} r={r} tags={tags} sources={sources} selected={sel.has(r.id)}
              onSelect={(on) => setSel((s) => { const n = new Set(s); on ? n.add(r.id) : n.delete(r.id); return n; })}
              notify={notify} reload={load} />
          ))}
        </div>
      )}

      {sel.size > 0 && (
        <div className="bulkbar" role="region" aria-label="Bulk actions">
          <label className="check-all"><input type="checkbox" className="check" checked={sel.size === allIds.length} onChange={(e) => setSel(e.target.checked ? new Set(allIds) : new Set())} />{sel.size} selected</label>
          <span className="spacer" />
          <button className="btn ghost" onClick={() => bulk("snooze")}><Icon name="clock" size={16} />Snooze</button>
          <button className="btn ghost danger" onClick={() => bulk("reject")}><Icon name="x" size={16} />Reject</button>
          <button className="btn primary" onClick={() => bulk("approve")} title="Uses the suggested library and the best-seeded version at your preferred quality"><Icon name="check" size={16} />Approve preferred</button>
        </div>
      )}
    </>
  );
}
