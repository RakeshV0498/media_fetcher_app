import { FormEvent, useState } from "react";
import { api } from "../api";
import { Icon } from "../ui";

export function Login({ onLogin }: { onLogin: (u: string) => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api<{ user: string }>("/api/auth/login", "POST", { username, password });
      onLogin(r.user);
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <form className="login" onSubmit={submit}>
        <span className="brand-mark big"><Icon name="film" size={28} /></span>
        <h1>Media Fetcher</h1>
        <p className="sub">Sign in to review new releases</p>
        <label className="field">Username<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" /></label>
        <label className="field">Password<input type="password" autoFocus value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
        {err && <p className="form-error"><Icon name="alert" size={16} />{err}</p>}
        <button className="btn primary block" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </div>
  );
}
