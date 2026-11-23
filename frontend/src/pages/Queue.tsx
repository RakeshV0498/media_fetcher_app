import { useCallback, useEffect, useState } from "react";
import { api, fmtEp, fmtSize, Release, Source, Tag } from "../api";
import type { ToastFn } from "../App";

function Card({ r, tags, sources, selected, onSelect, notify, reload }: {
  r: Release; tags: Tag[]; sources: Source[]; selected: boolean;
  onSelect: (on: boolean) => void; notify: ToastFn; reload: () => void;
}) {
  const [variantId, setVariantId] = useState<number | null>(null);
  const [tagId, setTagId] = useState<number | null>(r.suggested_tag_id);
  const [all, setAll] = useState<Release | null>(null);
  const shown = (all ?? r).variants;
  const srcName = (id: number) => sources.find((s) => s.id === id)?.name ?? `#${id}`;

  const act = async (path: string, body?: unknown, ok = "Done") => {
    try {
      await api(`/api/releases/${r.id}/${path}`, "POST", body ?? {});
      notify(ok);
      reload();
    } catch (e) {
      notify((e as Error).message, true);
    }
  };

  return (
    <article className="card">
      <div className="media">
        {r.poster_url && <img className="poster" src={r.poster_url} alt="" loading="lazy" />}
        <div className="grow">
      <div className="row">
        {r.status === "new" && <input type="checkbox" checked={selected} onChange={(e) => onSelect(e.target.checked)} aria-label="select" />}
        <h3>{r.title} {r.year ?? ""} <span className="muted">{fmtEp(r)}</span></h3>
        <span className="badge">{r.kind}</span>
      </div>
      {r.overview && <p className="muted overview">{r.overview}</p>}
      <ul className="variants">
        {shown.map((v) => (
          <li key={v.id}>
            <label>
              <input type="radio" name={`v${r.id}`} checked={variantId === v.id} onChange={() => setVariantId(v.id)} />
              <span className="badge q">{v.quality ?? "?"}</span>
              <span>{fmtSize(v.size_bytes)}</span>
              <span title="seeders">▲ {v.seeders ?? "–"}</span>
              <span className="muted">{[v.codec, v.language].filter(Boolean).join(" · ")}</span>
              <span className="muted">{srcName(v.source_id)}</span>
            </label>
          </li>
        ))}
      </ul>
      {r.variant_count > shown.length && (
        <button className="link" onClick={() => api<Release[]>(`/api/releases?status=${r.status}&all_variants=true`).then((l) => setAll(l.find((x) => x.id === r.id) ?? null))}>
          Show all {r.variant_count} variants
        </button>
      )}
      {r.status === "new" || r.status === "snoozed" ? (
        <div className="row actions">
          <select value={tagId ?? ""} onChange={(e) => setTagId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">Select tag…</option>
            {tags.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <button className="primary" disabled={variantId == null || tagId == null}
            title={variantId == null ? "Pick a variant first" : ""}
            onClick={() => act("approve", { variant_id: variantId, tag_id: tagId }, "Approved")}>Approve</button>
          <button onClick={() => act("reject", undefined, "Rejected")}>Reject</button>
          <button onClick={() => act("snooze", { hours: 24 }, "Snoozed 24h")}>Snooze</button>
        </div>
      ) : null}
        </div>
      </div>
    </article>
  );
}

export function Queue({ notify }: { notify: ToastFn }) {
  const [releases, setReleases] = useState<Release[]>([]);
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
      notify(`${r.done.length} done${sk ? `, ${sk} skipped (${Object.values(r.skipped)[0]})` : ""}`, sk > 0);
      load();
    } catch (e) { notify((e as Error).message, true); }
  };

  return (
    <>
      <div className="filters row">
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          {["new", "snoozed", "approved", "rejected"].map((s) => <option key={s}>{s}</option>)}
        </select>
        <select value={tagF} onChange={(e) => setTagF(e.target.value)}>
          <option value="">All tags</option>{tags.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
        <select value={srcF} onChange={(e) => setSrcF(e.target.value)}>
          <option value="">All sources</option>{sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <input placeholder="Search title…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {sel.size > 0 && (
        <div className="bulk row">
          <span>{sel.size} selected</span>
          <button className="primary" onClick={() => bulk("approve")} title="Uses suggested tag + top-ranked variant at your preferred quality">Approve (preferred quality)</button>
          <button onClick={() => bulk("reject")}>Reject</button>
          <button onClick={() => bulk("snooze")}>Snooze</button>
        </div>
      )}
      {releases.length === 0 && <p className="muted">Nothing here.</p>}
      <div className="grid">
        {releases.map((r) => (
          <Card key={`${r.id}-${r.variants.length}`} r={r} tags={tags} sources={sources} selected={sel.has(r.id)}
            onSelect={(on) => setSel((s) => { const n = new Set(s); on ? n.add(r.id) : n.delete(r.id); return n; })}
            notify={notify} reload={load} />
        ))}
      </div>
    </>
  );
}
