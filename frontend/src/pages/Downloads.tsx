import { useEffect, useState } from "react";
import { api, Download, fmtEp } from "../api";
import type { ToastFn } from "../App";
import { Empty, Icon, PageHead, qualityClass } from "../ui";

const fmtEta = (s: number | null) => (s == null ? "–" : s >= 3600 ? `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m` : s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`);
const LABEL: Record<string, string> = { downloading: "Downloading", paused: "Paused", done: "Filed", moving: "Filing…", failed: "Failed", needs_attention: "Needs attention", duplicate: "Duplicate", queued: "Queued" };
const TONE: Record<string, string> = { downloading: "info", paused: "muted", done: "good", moving: "info", failed: "bad", needs_attention: "warn", duplicate: "warn", queued: "muted" };

export function Downloads({ notify }: { notify: ToastFn }) {
  const [rows, setRows] = useState<Download[] | null>(null);
  useEffect(() => {
    const tick = () => api<Download[]>("/api/downloads").then(setRows).catch(() => {});
    tick();
    const id = setInterval(tick, 3000);
    return () => clearInterval(id);
  }, []);

  const setSeason = (id: number) => {
    const v = prompt("Season number for this show?");
    if (!v || isNaN(Number(v))) return;
    const ep = prompt("Episode number (leave blank to keep detected)?");
    api<{ status: string; error: string }>(`/api/downloads/${id}/set-season`, "POST", { season: Number(v), episode: ep ? Number(ep) : null })
      .then((r) => notify(r.error || `Filed (${r.status})`, !!r.error)).catch((e) => notify(e.message, true));
  };
  const act = (id: number, a: string) =>
    (a === "remove" ? api(`/api/downloads/${id}`, "DELETE") : api(`/api/downloads/${id}/${a}`, "POST")).catch((e) => notify(e.message, true));

  return (
    <>
      <PageHead title="Downloads" sub="Live progress from your download nodes. Finished files are filed into your library automatically." />
      {rows === null ? <div className="card skeleton" /> : rows.length === 0 ? (
        <Empty icon="download" title="No downloads yet" hint="Approve a release in Review and it shows up here." />
      ) : (
        <div className="stack">
          {rows.map((d) => (
            <article key={d.id} className="card dl">
              <div className="dl-head">
                <div className="dl-title">
                  <h3>{d.title}</h3>
                  {fmtEp({ season: d.season, episode: d.episode, absolute_episode: null }) && <span className="chip mono">{fmtEp({ season: d.season, episode: d.episode, absolute_episode: null })}</span>}
                  <span className={`q ${qualityClass(d.quality)}`}>{d.quality ?? "?"}</span>
                  <span className="chip ghost">{d.tag}</span>
                  <span className="chip ghost">{d.node || "local"}</span>
                </div>
                <span className={`status ${TONE[d.status] ?? "muted"}`}><i />{LABEL[d.status] ?? d.status}</span>
              </div>
              <div className={`progress ${TONE[d.status] ?? ""}`} role="progressbar" aria-valuenow={Math.round(d.progress * 100)} aria-valuemin={0} aria-valuemax={100}>
                <div style={{ width: `${Math.round(d.progress * 100)}%` }} />
              </div>
              <div className="dl-stats">
                <span className="mono">{Math.round(d.progress * 100)}%</span>
                <span className="mono">{(d.speed / 1e6).toFixed(1)} MB/s</span>
                <span className="mono">ETA {fmtEta(d.eta)}</span>
                <span className="spacer" />
                {d.status === "paused" ? <button className="btn sm" onClick={() => act(d.id, "resume")}><Icon name="play" size={14} />Resume</button>
                  : d.status === "downloading" && <button className="btn sm" onClick={() => act(d.id, "pause")}><Icon name="pause" size={14} />Pause</button>}
                {["failed", "needs_attention", "duplicate"].includes(d.status) && <button className="btn sm" onClick={() => act(d.id, "retry")}><Icon name="refresh" size={14} />Retry</button>}
                {d.status === "needs_attention" && <button className="btn sm" onClick={() => setSeason(d.id)}><Icon name="pencil" size={14} />Set season</button>}
                <button className="btn sm ghost danger" onClick={() => act(d.id, "remove")}><Icon name="trash" size={14} />Remove</button>
              </div>
              {d.error && <p className="note bad"><Icon name="alert" size={16} />{d.error}</p>}
              {d.files.length > 0 && <p className="note"><Icon name="check" size={16} /><span className="mono">{d.files.join(", ")}</span></p>}
            </article>
          ))}
        </div>
      )}
    </>
  );
}
