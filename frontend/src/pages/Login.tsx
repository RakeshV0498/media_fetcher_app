import { FormEvent, useState } from "react";
import { api } from "../api";

export function Login({ onLogin }: { onLogin: (u: string) => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const r = await api<{ user: string }>("/api/auth/login", "POST", { username, password });
      onLogin(r.user);
    } catch (x) {
      setErr((x as Error).message);
    }
  };

  return (
    <form className="card login" onSubmit={submit}>
      <h1>Media Fetcher</h1>
      <label>Username<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" /></label>
      <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
      {err && <p className="err">{err}</p>}
      <button className="primary">Sign in</button>
    </form>
  );
}
