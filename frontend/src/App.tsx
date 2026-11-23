import { useCallback, useEffect, useState } from "react";
import { api, setUnauthorizedHandler } from "./api";
import { Icon, IconName } from "./ui";
import { Login } from "./pages/Login";
import { Queue } from "./pages/Queue";
import { Sources } from "./pages/Sources";
import { Tags } from "./pages/Tags";
import { Downloads } from "./pages/Downloads";
import { Nodes } from "./pages/Nodes";

const PAGES = {
  Queue: { C: Queue, icon: "inbox" as IconName, label: "Review" },
  Downloads: { C: Downloads, icon: "download" as IconName, label: "Downloads" },
  Sources: { C: Sources, icon: "rss" as IconName, label: "Sources" },
  Tags: { C: Tags, icon: "tag" as IconName, label: "Tags" },
  Nodes: { C: Nodes, icon: "server" as IconName, label: "Nodes" },
};
type PageName = keyof typeof PAGES;

export type ToastFn = (msg: string, bad?: boolean) => void;

function useTheme() {
  const [theme, setTheme] = useState<string>(() => {
    try { return localStorage.getItem("theme") ?? "auto"; } catch { return "auto"; }
  });
  useEffect(() => {
    const root = document.documentElement;
    theme === "auto" ? root.removeAttribute("data-theme") : root.setAttribute("data-theme", theme);
    try { localStorage.setItem("theme", theme); } catch { /* storage unavailable */ }
  }, [theme]);
  const dark = theme === "dark" || (theme === "auto" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  return { dark, toggle: () => setTheme(dark ? "light" : "dark") };
}

export default function App() {
  const [user, setUser] = useState<string | null | undefined>(undefined);
  const [page, setPage] = useState<PageName>("Queue");
  const [toast, setToast] = useState<{ msg: string; bad: boolean } | null>(null);
  const theme = useTheme();

  const notify: ToastFn = useCallback((msg, bad = false) => {
    setToast({ msg, bad });
    setTimeout(() => setToast(null), 5000);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null));
    api<{ user: string }>("/api/auth/me").then((r) => setUser(r.user)).catch(() => setUser(null));
  }, []);

  if (user === undefined) return <div className="boot"><div className="spinner" /></div>;
  if (user === null) return <Login onLogin={setUser} />;

  const { C } = PAGES[page];
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark"><Icon name="film" size={20} /></span><span>Media Fetcher</span></div>
        <nav aria-label="Main">
          {(Object.keys(PAGES) as PageName[]).map((p) => (
            <button key={p} className={`nav-item ${p === page ? "active" : ""}`} onClick={() => setPage(p)} aria-current={p === page ? "page" : undefined}>
              <Icon name={PAGES[p].icon} /><span>{PAGES[p].label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <button className="nav-item" onClick={theme.toggle} title="Toggle theme"><Icon name={theme.dark ? "sun" : "moon"} /><span>{theme.dark ? "Light mode" : "Dark mode"}</span></button>
          <button className="nav-item" onClick={() => api("/api/auth/logout", "POST").then(() => setUser(null))}><Icon name="logout" /><span>Log out · {user}</span></button>
        </div>
      </aside>
      <main><C notify={notify} /></main>
      {toast && <div className={`toast ${toast.bad ? "bad" : ""}`} role="status"><Icon name={toast.bad ? "alert" : "check"} />{toast.msg}</div>}
    </div>
  );
}
