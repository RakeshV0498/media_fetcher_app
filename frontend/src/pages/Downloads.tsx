import { useEffect, useState } from "react";
import { api, Download, fmtEp } from "../api";
import type { ToastFn } from "../App";

const fmtEta = (s: number | null) => (s == null ? "–" : s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`);

export function Downloads({ notify }: { notify: ToastFn }) {
  const [rows, setRows] = useState<Download[]>([]);
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
    api<{ status: string; error: string }>(`/api/downloads/${id}/set-season`, "POST",
      { season: Number(v), episode: ep ? Number(ep) : null })
      .then((r) => notify(r.error || `Filed (${r.status})`, !!r.error)).catch((e) => notify(e.message, true));
  };
  const act = (id: number, a: string) =>
    (a === "remove" ? api(`/api/downloads/${id}`, "DELETE") : api(`/api/downloads/${id}/${a}`, "POST")).catch((e) => notify(e.message, true));

  return (
    <>
      {rows.length === 0 && <p className="muted">No downloads yet.</p>}
      {rows.map((d) => (
        <article key={d.id} className="card">
          <div className="row">
            <h3>{d.title} <span className="muted">{fmtEp({ season: d.season, episode: d.episode, absolute_episode: null })}</span></h3>
            <span className="badge q">{d.quality ?? "?"}</span><span className="badge">{d.tag}</span><span className="badge">{d.node}</span>
            <span className={`badge st-${d.status}`}>{d.status}</span>
          </div>
          <progress value={d.progress} max={1} />
          {d.files.length > 0 && <p className="muted">Filed: {d.files.join(", ")}</p>}
          <p className="muted">{Math.round(d.progress * 100)}% · {(d.speed / 1e6).toFixed(1)} MB/s · ETA {fmtEta(d.eta)} {d.error && <span className="err">{d.error}</span>}</p>
          <div className="row">
            {d.status === "paused" ? <button onClick={() => act(d.id, "resume")}>Resume</button> : d.status === "downloading" && <button onClick={() => act(d.id, "pause")}>Pause</button>}
            {["failed", "needs_attention", "duplicate"].includes(d.status) && <button onClick={() => act(d.id, "retry")}>Retry</button>}
            {d.status === "needs_attention" && <button onClick={() => setSeason(d.id)}>Set season…</button>}
            <button onClick={() => act(d.id, "remove")}>Remove</button>
          </div>
        </article>
      ))}
    </>
  );
}
