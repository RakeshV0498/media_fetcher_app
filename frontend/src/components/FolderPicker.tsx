import { useCallback, useEffect, useState } from "react";
import { api, BrowseResult } from "../api";
import { Icon } from "../ui";

/** Browse folders on a node (limited server-side to its allowed media roots) and pick one. */
export function FolderPicker({ nodeId, start, onPick, onClose }: {
  nodeId: number; start: string; onPick: (path: string) => void; onClose: () => void;
}) {
  const [cur, setCur] = useState<BrowseResult | null>(null);
  const [err, setErr] = useState("");
  const [newName, setNewName] = useState("");

  const go = useCallback((path: string) => {
    api<BrowseResult>(`/api/nodes/${nodeId}/browse?path=${encodeURIComponent(path)}`)
      .then((r) => { setCur(r); setErr(""); })
      .catch((e) => { setErr((e as Error).message); if (path) go(""); });
  }, [nodeId]);
  useEffect(() => go(start), [go, start]);

  const join = (name: string) => (cur?.absolute ? name : `${cur?.path.replace(/\/$/, "")}/${name}`);
  const make = async () => {
    if (!cur || cur.absolute || !newName.trim()) return;
    try {
      const r = await api<{ path: string }>(`/api/nodes/${nodeId}/mkdir`, "POST", { path: join(newName.trim()) });
      setNewName(""); go(r.path);
    } catch (e) { setErr((e as Error).message); }
  };

  return (
    <div className="modal-back" onClick={onClose} role="presentation">
      <div className="modal" role="dialog" aria-modal="true" aria-label="Choose a folder" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head"><h3>Choose a folder</h3><button className="btn ghost sm" onClick={onClose} aria-label="Close"><Icon name="x" size={16} /></button></div>
        <p className="crumb mono">{cur?.absolute ? "Media roots on this node" : cur?.path || "…"}</p>
        {err && <p className="form-error"><Icon name="alert" size={16} />{err}</p>}
        <ul className="dirlist">
          {cur && cur.parent !== null && <li><button onClick={() => go(cur.parent!)}><Icon name="folder" size={16} />.. (up)</button></li>}
          {cur?.dirs.map((d) => (
            <li key={d}><button onClick={() => go(join(d))}><Icon name="folder" size={16} />{cur.absolute ? d : d}</button></li>
          ))}
          {cur && cur.dirs.length === 0 && <li className="muted pad-s">No sub-folders here.</li>}
        </ul>
        {cur && !cur.absolute && (
          <div className="row-inline">
            <input placeholder="New folder name" value={newName} onChange={(e) => setNewName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && make()} />
            <button className="btn" onClick={make} disabled={!newName.trim()}><Icon name="plus" size={16} />Create</button>
          </div>
        )}
        <div className="form-actions">
          <button className="btn primary" disabled={!cur || cur.absolute} onClick={() => cur && onPick(cur.path)}><Icon name="check" size={16} />Use this folder</button>
          <button className="btn ghost" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
