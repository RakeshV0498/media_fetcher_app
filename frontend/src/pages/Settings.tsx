import { useCallback, useEffect, useState } from "react";
import { api, AppField, NodeInfo, Tag, VpnForm } from "../api";
import type { ToastFn } from "../App";
import { FolderPicker } from "../components/FolderPicker";
import { Icon, PageHead } from "../ui";

const TABS = [
  ["general", "General"], ["integrations", "Integrations"], ["telegram", "Telegram"], ["downloads", "Downloads"],
  ["libraries", "Libraries"], ["nodes", "Nodes & VPN"], ["security", "Security"],
] as const;
type TabId = (typeof TABS)[number][0];

/* ---------- generic form for the key/value settings ---------- */
function FieldsForm({ group, fields, reload, notify, tests = [], intro }: {
  group: string; fields: AppField[]; reload: () => void; notify: ToastFn;
  tests?: { name: string; label: string }[]; intro?: string;
}) {
  const mine = fields.filter((f) => f.group === group);
  const [edits, setEdits] = useState<Record<string, string | boolean>>({});
  const [replacing, setReplacing] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const dirty = Object.keys(edits).length > 0;
  const val = (f: AppField) => (f.key in edits ? edits[f.key] : (f.value ?? ""));
  const edit = (f: AppField, v: string | boolean) => {
    if (f.key === "downloads_enabled" && v === true && !confirm("Enable real downloads? Approvals will start sending torrents to your nodes (only when the VPN check passes).")) return;
    setEdits((e) => ({ ...e, [f.key]: v }));
  };

  const put = async (body: { values?: Record<string, unknown>; clear?: string[] }, ok: string) => {
    setBusy(true);
    try { await api("/api/app-settings", "PUT", body); notify(ok); setEdits({}); setReplacing(new Set()); reload(); }
    catch (e) { notify((e as Error).message, true); } finally { setBusy(false); }
  };
  const runTest = async (name: string) => {
    if (dirty) return notify("Save your changes first, then test.", true);
    try { const r = await api<{ ok: boolean; message: string }>(`/api/app-settings/test/${name}`, "POST"); notify(r.message, !r.ok); }
    catch (e) { notify((e as Error).message, true); }
  };

  return (
    <section className="card form-card">
      {intro && <p className="sub">{intro}</p>}
      <div className="form-grid">
        {mine.map((f) => (
          <div key={f.key} className={`field ${f.kind === "bool" ? "toggle-field" : ""} ${f.danger ? "danger-field" : ""}`}>
            {f.kind === "bool" ? (
              <label className="switch-row">
                <span><span className="lbl">{f.label}</span>{f.help && <span className="hint">{f.help}</span>}</span>
                <input type="checkbox" className="switch" checked={Boolean(val(f))} onChange={(e) => edit(f, e.target.checked)} />
              </label>
            ) : (
              <>
                <span className="lbl">{f.label}
                  {f.source === "db" && f.kind !== "secret" && <button type="button" className="link inline" onClick={() => put({ clear: [f.key] }, "Reset to the .env default")}>reset</button>}
                </span>
                {f.kind === "secret" ? (
                  f.set && !replacing.has(f.key) ? (
                    <div className="secret-set">
                      <span className="mono">{f.unreadable ? "unreadable (APP_SECRET changed) - enter again" : "•••••••••••• saved"}</span>
                      <button type="button" className="link" onClick={() => setReplacing(new Set(replacing).add(f.key))}>Replace</button>
                      <button type="button" className="link danger-link" onClick={() => confirm(`Remove ${f.label}?`) && put({ clear: [f.key] }, `${f.label} removed`)}>Remove</button>
                    </div>
                  ) : (
                    <input type="password" autoComplete="off" placeholder="Paste value" value={String(edits[f.key] ?? "")} onChange={(e) => edit(f, e.target.value)} />
                  )
                ) : f.kind === "select" ? (
                  <div className="select-wrap"><select value={String(val(f))} onChange={(e) => edit(f, e.target.value)}>{f.options.map((o) => <option key={o}>{o}</option>)}</select><Icon name="chevron" size={16} /></div>
                ) : (
                  <input type={f.kind === "int" || f.kind === "float" ? "number" : "text"} step={f.kind === "float" ? "0.1" : undefined}
                    className={f.kind === "url" ? "mono" : ""} value={String(val(f))} onChange={(e) => edit(f, e.target.value)} />
                )}
                {f.help && <span className="hint">{f.help}{f.source === "env" && f.kind !== "secret" ? "" : ""}</span>}
              </>
            )}
          </div>
        ))}
      </div>
      <div className="form-actions">
        <button className="btn primary" disabled={!dirty || busy} onClick={() => put({ values: edits }, "Settings saved")}><Icon name="check" size={16} />Save changes</button>
        {dirty && <button className="btn ghost" onClick={() => { setEdits({}); setReplacing(new Set()); }}>Discard</button>}
        {tests.map((t) => <button key={t.name} className="btn" onClick={() => runTest(t.name)}><Icon name="refresh" size={16} />{t.label}</button>)}
      </div>
    </section>
  );
}

/* ---------- Libraries (tags -> node + folder) ---------- */
function Libraries({ notify }: { notify: ToastFn }) {
  const [tags, setTags] = useState<Tag[] | null>(null);
  const [nodes, setNodes] = useState<NodeInfo[]>([]);
  const [picker, setPicker] = useState<Tag | null>(null);
  useEffect(() => { api<Tag[]>("/api/tags").then(setTags); api<NodeInfo[]>("/api/nodes").then(setNodes); }, []);
  const patch = (id: number, p: Partial<Tag>) => setTags((l) => l && l.map((t) => (t.id === id ? { ...t, ...p } : t)));
  const save = (t: Tag) => api(`/api/tags/${t.id}`, "PUT", t).then(() => notify(`Saved ${t.name}`)).catch((e) => notify(e.message, true));
  return (
    <>
      <p className="sub tab-intro">Each tag sends downloads to a node and files them into a library folder on that Pi. Folders are browsed on the node itself and limited to its allowed media roots.</p>
      <div className="grid forms">
        {tags?.map((t) => (
          <article key={t.id} className="card form-card">
            <div className="title-row"><h3>{t.name}</h3><span className={`chip kind-${t.kind}`}>{t.kind}</span></div>
            <label className="field"><span className="lbl">Node</span>
              <div className="select-wrap"><select value={t.node_id ?? ""} onChange={(e) => patch(t.id, { node_id: e.target.value ? Number(e.target.value) : null })}>
                <option value="">— none —</option>{nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}</select><Icon name="chevron" size={16} /></div></label>
            <label className="field"><span className="lbl">qBittorrent category</span><input value={t.qbit_category} onChange={(e) => patch(t.id, { qbit_category: e.target.value })} /></label>
            <div className="field"><span className="lbl">Final folder</span>
              <div className="row-inline">
                <input className="mono" value={t.final_path} onChange={(e) => patch(t.id, { final_path: e.target.value })} />
                <button className="btn" disabled={!t.node_id} title={t.node_id ? "" : "Pick a node first"} onClick={() => setPicker(t)}><Icon name="folder" size={16} />Browse</button>
              </div></div>
            <div className="form-actions"><button className="btn primary" onClick={() => save(t)}><Icon name="check" size={16} />Save</button></div>
          </article>
        ))}
      </div>
      {picker && picker.node_id && (
        <FolderPicker nodeId={picker.node_id} start={picker.final_path} onClose={() => setPicker(null)}
          onPick={(p) => { patch(picker.id, { final_path: p }); setPicker(null); notify("Folder selected - press Save on the card"); }} />
      )}
    </>
  );
}

/* ---------- Nodes & VPN ---------- */
const EMPTY_VPN: VpnForm = { provider: "", type: "wireguard", countries: "", port_forwarding: false, wireguard_addresses: "",
  wireguard_private_key: "", openvpn_user: "", openvpn_password: "" };

function VpnSection({ node, notify, onApplied }: { node: NodeInfo; notify: ToastFn; onApplied: () => void }) {
  const [v, setV] = useState<VpnForm>(EMPTY_VPN);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api<VpnForm>(`/api/nodes/${node.id}/vpn`).then((r) => setV({ ...EMPTY_VPN, ...r, wireguard_private_key: "", openvpn_password: "" })); }, [node.id]);
  const set = (p: Partial<VpnForm>) => setV((x) => ({ ...x, ...p }));
  const save = async (apply: boolean) => {
    setBusy(true);
    try {
      const r = await api<{ message: string; applied: boolean; settings: VpnForm }>(`/api/nodes/${node.id}/vpn`, "PUT", { ...v, apply });
      notify(r.message, apply && !r.applied);
      setV({ ...EMPTY_VPN, ...r.settings, wireguard_private_key: "", openvpn_password: "" });
      if (r.applied) setTimeout(onApplied, 4000);
    } catch (e) { notify((e as Error).message, true); } finally { setBusy(false); }
  };
  const wg = v.type === "wireguard";
  return (
    <details className="vpn-box">
      <summary><Icon name="shield" size={16} />VPN provider settings</summary>
      <p className="sub">Stored encrypted. “Save &amp; apply” pushes them to this node's gluetun without a restart. Gluetun still needs a valid first-time config in <span className="mono">node.env</span> to start.</p>
      <div className="form-grid">
        <label className="field"><span className="lbl">Provider</span><input value={v.provider} placeholder="protonvpn, mullvad, nordvpn…" onChange={(e) => set({ provider: e.target.value })} /><span className="hint">Use the exact gluetun provider name.</span></label>
        <div className="field"><span className="lbl">Protocol</span><div className="segmented">{["wireguard", "openvpn"].map((t) => <button key={t} type="button" className={v.type === t ? "on" : ""} onClick={() => set({ type: t })}>{t}</button>)}</div></div>
        <label className="field"><span className="lbl">Server countries</span><input value={v.countries} placeholder="Netherlands, Germany" onChange={(e) => set({ countries: e.target.value })} /><span className="hint">Comma-separated. Pick P2P-capable locations.</span></label>
        <label className="switch-row field"><span><span className="lbl">Port forwarding</span><span className="hint">Only if your provider supports it.</span></span><input type="checkbox" className="switch" checked={v.port_forwarding} onChange={(e) => set({ port_forwarding: e.target.checked })} /></label>
        {wg ? (<>
          <div className="field"><span className="lbl">WireGuard private key</span><input type="password" autoComplete="off" placeholder={v.wireguard_private_key_set ? "•••••••• saved (leave blank to keep)" : "Paste key"} value={v.wireguard_private_key} onChange={(e) => set({ wireguard_private_key: e.target.value })} /></div>
          <label className="field"><span className="lbl">WireGuard addresses</span><input className="mono" value={v.wireguard_addresses} placeholder="10.2.0.2/32" onChange={(e) => set({ wireguard_addresses: e.target.value })} /></label>
        </>) : (<>
          <label className="field"><span className="lbl">OpenVPN user</span><input value={v.openvpn_user} onChange={(e) => set({ openvpn_user: e.target.value })} /></label>
          <div className="field"><span className="lbl">OpenVPN password</span><input type="password" autoComplete="off" placeholder={v.openvpn_password_set ? "•••••••• saved (leave blank to keep)" : "Password"} value={v.openvpn_password} onChange={(e) => set({ openvpn_password: e.target.value })} /></div>
        </>)}
      </div>
      <div className="form-actions">
        <button className="btn primary" disabled={busy} onClick={() => save(true)}><Icon name="check" size={16} />Save &amp; apply</button>
        <button className="btn" disabled={busy} onClick={() => save(false)}>Save only</button>
      </div>
    </details>
  );
}

function Nodes({ notify, fields, reload }: { notify: ToastFn; fields: AppField[]; reload: () => void }) {
  const [nodes, setNodes] = useState<NodeInfo[] | null>(null);
  const load = useCallback(() => { api<NodeInfo[]>("/api/nodes").then(setNodes).catch((e) => notify(e.message, true)); }, [notify]);
  useEffect(() => { load(); const id = setInterval(load, 15000); return () => clearInterval(id); }, [load]);
  const patch = (id: number, p: Partial<NodeInfo>) => setNodes((l) => l && l.map((n) => (n.id === id ? { ...n, ...p } : n)));
  const save = (n: NodeInfo) => api("/api/nodes/" + n.id, "PUT", { agent_url: n.agent_url, qbit_url: n.qbit_url, download_dir: n.download_dir, max_concurrent: n.max_concurrent })
    .then(() => { notify(`Saved ${n.name}`); load(); }).catch((e) => notify(e.message, true));
  const test = async (n: NodeInfo) => {
    try {
      const r = await api<{ checks: { name: string; ok: boolean; message: string }[] }>(`/api/nodes/${n.id}/test`, "POST");
      const bad = r.checks.filter((c) => !c.ok);
      notify(bad.length ? bad.map((c) => `${c.name}: ${c.message}`).join(" · ") : "All checks passed", bad.length > 0);
    } catch (e) { notify((e as Error).message, true); }
  };
  return (
    <>
      <p className="sub tab-intro">One download node per Pi. A VPN is optional; if you turn on “Require VPN to download”, downloads only run when the node's VPN is verified. Allowed media folders (<span className="mono">MEDIA_ROOTS</span>) are a security boundary and stay in each Pi's <span className="mono">node.env</span>.</p>
      <div className="grid forms">
        {nodes?.map((n) => (
          <article key={n.id} className="card form-card">
            <div className="title-row">
              <span className={`shield ${n.vpn_ok ? "good" : "bad"}`}><Icon name="shield" size={20} /></span><h3>{n.name}</h3>
              <span className={`status ${n.vpn_ok ? "good" : n.vpn_required ? "bad" : "warn"}`}><i />{n.vpn_ok ? "VPN protected" : n.vpn_required ? "VPN not verified" : "No VPN (allowed)"}</span>
            </div>
            {!n.vpn_ok && n.vpn_required && <p className="note bad"><Icon name="alert" size={16} />{n.vpn}</p>}
            {!n.vpn_ok && !n.vpn_required && <p className="note"><Icon name="alert" size={16} />Downloads from this node use your home IP. Turn on "Require VPN to download" in the Downloads tab to enforce a VPN.</p>}
            <dl className="kv"><div><dt>VPN IP</dt><dd className="mono">{n.public_ip ?? "–"}</dd></div><div><dt>Home IP</dt><dd className="mono">{n.home_ip ?? "–"}</dd></div></dl>
            <label className="field"><span className="lbl">Node agent URL</span><input className="mono" value={n.agent_url} placeholder="http://pi4.lan:8800" onChange={(e) => patch(n.id, { agent_url: e.target.value })} /></label>
            <label className="field"><span className="lbl">qBittorrent WebUI URL</span><input className="mono" value={n.qbit_url} placeholder="http://pi4.lan:8080" onChange={(e) => patch(n.id, { qbit_url: e.target.value })} /></label>
            <label className="field"><span className="lbl">Download folder on this Pi</span><input className="mono" value={n.download_dir} placeholder="blank = the node's DOWNLOADS_DIR" onChange={(e) => patch(n.id, { download_dir: e.target.value })} /><span className="hint">Where qBittorrent saves while downloading. Finished files are then moved into the library folder. Put it on the same disk as your library for instant moves.</span></label>
            <label className="field"><span className="lbl">Max concurrent downloads</span><input type="number" min={1} value={n.max_concurrent} onChange={(e) => patch(n.id, { max_concurrent: Number(e.target.value) })} /></label>
            <div className="form-actions"><button className="btn primary" onClick={() => save(n)}><Icon name="check" size={16} />Save</button><button className="btn" onClick={() => test(n)}><Icon name="refresh" size={16} />Test connection</button></div>
            <VpnSection node={n} notify={notify} onApplied={load} />
          </article>
        ))}
      </div>
      <h3 className="section-title">Node credentials</h3>
      <FieldsForm group="downloads" fields={fields.filter((f) => ["qbit_username", "qbit_password", "node_agent_token"].includes(f.key))} reload={reload} notify={notify} />
    </>
  );
}

/* ---------- Security ---------- */
function Security({ notify, fields, reload }: { notify: ToastFn; fields: AppField[]; reload: () => void }) {
  const [cur, setCur] = useState(""); const [next, setNext] = useState(""); const [again, setAgain] = useState("");
  const change = async () => {
    if (next !== again) return notify("The new passwords don't match", true);
    try { await api("/api/app-settings/password", "POST", { current: cur, new: next }); notify("Password changed"); setCur(""); setNext(""); setAgain(""); }
    catch (e) { notify((e as Error).message, true); }
  };
  return (
    <div className="stack">
      <FieldsForm group="security" fields={fields} reload={reload} notify={notify} intro="Changing the username takes effect on your next sign-in." />
      <section className="card form-card">
        <h3>Change password</h3>
        <div className="form-grid">
          <label className="field wide"><span className="lbl">Current password</span><input type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} /></label>
          <label className="field"><span className="lbl">New password</span><input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} /><span className="hint">At least 10 characters.</span></label>
          <label className="field"><span className="lbl">Repeat new password</span><input type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} /></label>
        </div>
        <div className="form-actions"><button className="btn primary" disabled={!cur || !next} onClick={change}><Icon name="check" size={16} />Change password</button></div>
      </section>
    </div>
  );
}

/* ---------- Page ---------- */
export function SettingsPage({ notify }: { notify: ToastFn }) {
  const [tab, setTab] = useState<TabId>(() => (TABS.find(([id]) => id === location.hash.slice(1))?.[0] ?? "general"));
  const [fields, setFields] = useState<AppField[] | null>(null);
  const [quality, setQuality] = useState("1080p");
  const reload = useCallback(() => { api<{ fields: AppField[] }>("/api/app-settings").then((r) => setFields(r.fields)).catch((e) => notify(e.message, true)); }, [notify]);
  useEffect(() => { reload(); api<{ preferred_quality: string }>("/api/settings").then((s) => setQuality(s.preferred_quality)); }, [reload]);
  const pick = (t: TabId) => { setTab(t); history.replaceState(null, "", `#${t}`); };
  const setQ = (q: string) => { setQuality(q); api("/api/settings", "PUT", { preferred_quality: q }).then(() => notify(`Preferred quality: ${q}`)); };

  return (
    <>
      <PageHead title="Settings" sub="Admin configuration. Changes apply immediately, no .env editing or restart needed." />
      <div className="tabs" role="tablist">
        {TABS.map(([id, label]) => <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? "on" : ""} onClick={() => pick(id)}>{label}</button>)}
      </div>
      {fields === null ? <div className="card skeleton" /> : (
        <div className="tab-body">
          {tab === "general" && <div className="stack">
            <section className="card pref"><div><h3>Preferred quality</h3><p className="sub">Used by “Approve preferred” and as the tie-break when ranking versions.</p></div>
              <div className="segmented">{["2160p", "1080p", "720p", "480p"].map((q) => <button key={q} className={quality === q ? "on" : ""} onClick={() => setQ(q)}>{q}</button>)}</div></section>
            <FieldsForm group="general" fields={fields} reload={reload} notify={notify} />
          </div>}
          {tab === "integrations" && <FieldsForm group="integrations" fields={fields} reload={reload} notify={notify} tests={[{ name: "tmdb", label: "Test TMDB" }, { name: "jellyfin", label: "Test Jellyfin" }]} intro="Metadata and your media server." />}
          {tab === "telegram" && <FieldsForm group="telegram" fields={fields} reload={reload} notify={notify} tests={[{ name: "telegram", label: "Send test message" }]} intro="New releases arrive with Approve / Reject buttons. Press Start in your bot's chat first." />}
          {tab === "downloads" && <FieldsForm group="downloads" fields={fields.filter((f) => !["qbit_username", "qbit_password", "node_agent_token"].includes(f.key))} reload={reload} notify={notify} intro="Real downloads need the master switch on. A VPN is optional: switch on “Require VPN to download” to also demand a passing VPN check." />}
          {tab === "libraries" && <Libraries notify={notify} />}
          {tab === "nodes" && <Nodes notify={notify} fields={fields} reload={reload} />}
          {tab === "security" && <Security notify={notify} fields={fields} reload={reload} />}
        </div>
      )}
    </>
  );
}
