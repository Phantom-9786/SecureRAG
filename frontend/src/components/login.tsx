"use client";
import { useRef, useState, type FormEvent } from "react";
import { api, type Profile } from "../lib/api";
import GoogleSignIn from "./google-signin";
export default function Login({
  onLogin,
  notice,
}: {
  onLogin: (profile: Profile) => void;
  notice: string;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  function begin() {
    if (lock.current) return false;
    lock.current = true;
    setBusy(true);
    return true;
  }
  function finish() {
    lock.current = false;
    setBusy(false);
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!begin()) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    setError("");
    try {
      const profile = await api<Profile>("/auth/login", {
        method: "POST",
        body: { email: data.get("email"), password: data.get("password") },
      });
      form.reset();
      onLogin(profile);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Sign in failed.");
    } finally {
      finish();
    }
  }
  return (
    <main className="login-page">
      <div className="login-story">
        <a className="brand" href="/">
          ◈ <span>SecureRAG</span>
        </a>
        <div>
          <p className="eyebrow">YOUR KNOWLEDGE, CONNECTED</p>
          <h1>
            Good answers start
            <br />
            with trusted sources.
          </h1>
          <p>
            Ask your company documents. Get clear answers with references you
            can open and verify.
          </p>
        </div>
        <p className="login-foot">
          Company knowledge. Within your permissions.
        </p>
      </div>
      <div className="login-panel">
        <form onSubmit={submit} className="login-form">
          <span className="badge">WORKSPACE ACCESS</span>
          <h2>Welcome back</h2>
          <p>Sign in with your company account.</p>
          {notice ? (
            <p role="status" className="notice">
              {notice}
            </p>
          ) : null}
          {error ? (
            <p role="alert" className="error">
              {error}
            </p>
          ) : null}
          <GoogleSignIn
            onLogin={onLogin}
            disabled={busy}
            begin={begin}
            finish={finish}
          />
          <label htmlFor="email">Email address</label>
          <input
            id="email"
            name="email"
            type="email"
            autoComplete="username"
            required
            maxLength={254}
            placeholder="you@company.com"
            disabled={busy}
          />
          <label htmlFor="password">Password</label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            maxLength={128}
            disabled={busy}
          />
          <button className="primary" disabled={busy}>
            {busy ? "Signing in…" : "Sign in →"}
          </button>
          <p className="small">
            Need access? Contact your workspace administrator.
          </p>
        </form>
      </div>
    </main>
  );
}
