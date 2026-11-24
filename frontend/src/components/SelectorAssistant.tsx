import { useState } from "react";
import { api } from "../api";
import type { ToastFn } from "../App";
import { Icon } from "../ui";

interface Row { title: string; link: string | null; magnet: boolean; torrent: boolean; size: string | null; seeders: number | null; leechers: number | null }
interface Candidate { selectors: Record<string, unknown>; score: number; count: number; notes: string[]; preview: Row[]; stats: Record<string, number>; two_level: boolean }
interface Result { candidates: Candidate[]; warnings: string[]; kind: string; rendered?: boolean; suggest_browser?: boolean }

function CandidateList({ result, picked, setPicked, onUse, useLabel }: {
  result: Result; picked: number; setPicked: (i: number) => void; onUse: (c: Candidate) => void; useLabel: string;
}) {
  return (
    <div className="cand-list">
      {result.warnings.map((w) => <p key={w} className="note warn-note"><Icon name="alert" size={16} /><span>{w}</span></p>)}
      {result.candidates.map((c, i) => (
        <div key={i} className={`cand ${picked === i ? "on" : ""}`} onClick={() => setPicked(i)}>
          <div className="row">
            <input type="radio" checked={picked === i} onChange={() => setPicked(i)} aria-label={`Candidate ${i + 1}`} />
            <strong>Option {i + 1}</strong>
            <span className="chip">{c.stats.items} entries</span>
            <span className={`chip ${c.stats.with_magnet + c.stats.with_torrent > 0 ? "good" : ""}`}>{c.stats.with_magnet} magnets · {c.stats.with_torrent} torrents</span>
            <span className="chip">{c.stats.with_size} sizes · {c.stats.with_seeders} seeders</span>
          </div>
          {picked === i && (
            <>
              {c.notes.map((n) => <p key={n} className="muted small">{n}</p>)}
              <div className="preview-wrap">
                <table className="preview">
                  <thead><tr><th>Title</th><th>Size</th><th>Seeds</th><th>Links</th></tr></thead>
                  <tbody>{c.preview.map((r, k) => (
                    <tr key={k}><td title={r.title}>{r.title}</td><td>{r.size ?? "–"}</td><td>{r.seeders ?? "–"}</td>
                      <td>{[r.magnet && "magnet", r.torrent && ".torrent", !r.magnet && !r.torrent && r.link && "page"].filter(Boolean).join(" · ") || "–"}</td></tr>
                  ))}</tbody>
                </table>
              </div>
              <pre className="mono selpre">{JSON.stringify(c.selectors, null, 2)}</pre>
              <button className="btn primary sm" onClick={(e) => { e.stopPropagation(); onUse(c); }}><Icon name="check" size={14} />{useLabel}</button>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

/** Looks at a page and proposes the selectors, with a preview of what a scan would read. */
export function SelectorAssistant({ url, userAgent, current, onApply, notify, browserEnabled, render, waitSelector, setFetch }: {
  url: string; userAgent: string; current: Record<string, unknown>;
  onApply: (selectors: Record<string, unknown>) => void; notify: ToastFn;
  browserEnabled: boolean; render: string; waitSelector: string; setFetch: (render: string, wait: string) => void;
}) {
  const [paste, setPaste] = useState(false);
  const [html, setHtml] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<Result | null>(null);
  const [picked, setPicked] = useState(0);
  const [used, setUsed] = useState<Candidate | null>(null);
  const [detailUrl, setDetailUrl] = useState("");
  const [detailPaste, setDetailPaste] = useState(false);
  const [detailHtml, setDetailHtml] = useState("");
  const [dres, setDres] = useState<Result | null>(null);
  const [dpicked, setDpicked] = useState(0);

  const run = async (kind: "listing" | "detail", forceBrowser = false) => {
    setBusy(true);
    try {
      const isDetail = kind === "detail";
      const useBrowser = forceBrowser || render === "browser";
      const fetchOpts = { render: useBrowser ? "browser" : "static", wait_selector: useBrowser && !isDetail && waitSelector ? waitSelector : null };
      const body = isDetail
        ? { kind, url: detailPaste ? null : detailUrl, html: detailPaste ? detailHtml : null, site_url: url, user_agent: userAgent, ...fetchOpts }
        : { kind, url: paste ? null : url, html: paste ? html : null, user_agent: userAgent, ...fetchOpts };
      const r = await api<Result>("/api/sources/analyze", "POST", body);
      if (isDetail) { setDres(r); setDpicked(0); } else { setRes(r); setPicked(0); setUsed(null); setDres(null); }
      if (forceBrowser && render !== "browser") setFetch("browser", waitSelector);
    } catch (e) { notify((e as Error).message, true); } finally { setBusy(false); }
  };

  const useListing = (c: Candidate) => {
    const keep = current.detail ? { detail: current.detail } : {};
    onApply({ ...c.selectors, ...keep });
    setUsed(c);
    if (c.two_level) setDetailUrl(c.preview.find((r) => r.link)?.link ?? "");
    notify(c.two_level ? "Listing selectors applied. Now detect the versions on a sample entry's page." : "Selectors applied - review them below, then save the source.");
  };
  const useDetail = (c: Candidate) => { onApply({ ...current, detail: c.selectors }); notify("Version selectors applied - review them below, then save the source."); };

  return (
    <div className="assistant">
      <div className="row">
        <h4><Icon name="search" size={16} /> Auto-detect selectors</h4>
        <span className="spacer" />
        <button type="button" className="link" onClick={() => setPaste(!paste)}>{paste ? "Fetch from the URL instead" : "Paste page HTML instead"}</button>
      </div>
      <p className="muted small">Reads the page and works out the selectors for you, with a preview of what a scan would extract. Use “paste” for sites that block scrapers, need a login or build the list with JavaScript (copy the page source, Ctrl+U).</p>
      {!paste && (
        <div className="fetch-opts">
          <label className="check-row">
            <input type="checkbox" className="check" checked={render === "browser"} disabled={!browserEnabled && render !== "browser"}
              onChange={(e) => setFetch(e.target.checked ? "browser" : "static", waitSelector)} />
            <span>Render with a browser <span className="muted small">(for sites that build their list with JavaScript)</span></span>
          </label>
          {!browserEnabled && <p className="muted small">Not available yet: turn on “Render JavaScript pages with a browser” in Settings → Integrations and start the browser service (see the README).</p>}
          {render === "browser" && <input className="mono" placeholder="Optional: wait for this element, e.g. li.row" value={waitSelector} onChange={(e) => setFetch("browser", e.target.value)} />}
        </div>
      )}
      {paste && <textarea className="mono" rows={5} placeholder="Paste the page's HTML here" value={html} onChange={(e) => setHtml(e.target.value)} />}
      <button type="button" className="btn" disabled={busy || (paste ? !html.trim() : !url)} onClick={() => run("listing")}>
        <Icon name="search" size={16} />{busy && !dres ? "Analyzing…" : "Analyze page"}
      </button>
      {res && res.suggest_browser && render !== "browser" && (
        <div className="note warn-note"><Icon name="alert" size={16} /><span>This page looks like it is built with JavaScript, which a plain fetch can't see.</span>
          <button type="button" className="btn sm" disabled={busy || !browserEnabled} title={browserEnabled ? "" : "Enable the browser in Settings → Integrations first"}
            onClick={() => run("listing", true)}><Icon name="search" size={14} />Try with the browser</button></div>
      )}
      {res && <CandidateList result={res} picked={picked} setPicked={setPicked} onUse={useListing} useLabel="Use these selectors" />}

      {used?.two_level && (
        <div className="assistant-step">
          <h4>Step 2: the versions page</h4>
          <p className="muted small">Pick one entry's page below (any title works) and I'll find the resolution blocks on it.</p>
          <div className="row-inline">
            {detailPaste
              ? <textarea className="mono" rows={4} placeholder="Paste the detail page's HTML" value={detailHtml} onChange={(e) => setDetailHtml(e.target.value)} />
              : <input className="mono" placeholder="https://… (an entry's page)" value={detailUrl} onChange={(e) => setDetailUrl(e.target.value)} />}
          </div>
          <div className="row">
            <button type="button" className="btn" disabled={busy || (detailPaste ? !detailHtml.trim() : !detailUrl)} onClick={() => run("detail")}>
              <Icon name="search" size={16} />{busy ? "Analyzing…" : "Detect versions"}
            </button>
            <button type="button" className="link" onClick={() => setDetailPaste(!detailPaste)}>{detailPaste ? "Use a URL instead" : "Paste HTML instead"}</button>
          </div>
          {dres && <CandidateList result={dres} picked={dpicked} setPicked={setDpicked} onUse={useDetail} useLabel="Use for versions" />}
        </div>
      )}
    </div>
  );
}
