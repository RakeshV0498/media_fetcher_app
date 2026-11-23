import { useCallback, useEffect, useState } from "react";
import { api, setUnauthorizedHandler } from "./api";
import { Login } from "./pages/Login";
import { Queue } from "./pages/Queue";
import { Sources } from "./pages/Sources";
import { Tags } from "./pages/Tags";
import { Downloads } from "./pages/Downloads";
import { Nodes } from "./pages/Nodes";

const PAGES = { Queue, Sources, Tags, Downloads, Nodes } as const;
type PageName = keyof typeof PAGES;

export interface ToastFn { (msg: string, bad?: boolean): void }

export default function App() {
  const [user, setUser] = useState<string | null | undefined>(undefined);
  const [page, setPage] = useState<PageName>("Queue");
  const [toast, setToast] = useState<{ msg: string; bad: boolean } | null>(null);

  const notify: ToastFn = useCallback((msg, bad = false) => {
    setToast({ msg, bad });
    setTimeout(() => setToast(null), 5000);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null));
    api<{ user: string }>("/api/auth/me").then((r) => setUser(r.user)).catch(() => setUser(null));
  }, []);

  if (user === undefined) return <p className="muted pad">Loading…</p>;
  if (user === null) return <Login onLogin={setUser} />;

  const Page = PAGES[page];
  return (
    <>
      <header>
        <strong>Media Fetcher</strong>
        <nav>
          {(Object.keys(PAGES) as PageName[]).map((p) => (
            <button key={p} className={p === page ? "active" : ""} onClick={() => setPage(p)}>{p}</button>
          ))}
        </nav>
        <button onClick={() => api("/api/auth/logout", "POST").then(() => setUser(null))}>Log out</button>
      </header>
      <main><Page notify={notify} /></main>
      {toast && <div className={`toast ${toast.bad ? "bad" : ""}`} role="status">{toast.msg}</div>}
    </>
  );
}
