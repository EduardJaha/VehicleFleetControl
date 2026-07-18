"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const { login, registerFirstAdmin } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      if (mode === "register") {
        await registerFirstAdmin({ email, full_name: fullName, password });
      } else {
        await login(email, password);
      }
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="loginPage">
      <section className="loginCard">
        <div>
          <h1>Vehicle Fleet Control</h1>
          <p className="muted">{mode === "register" ? "Create the first Admin user for this local database." : "Sign in to continue."}</p>
        </div>

        {error && <div className="error">{error}</div>}

        <form className="form fullWidthForm" onSubmit={submit}>
          {mode === "register" && (
            <div className="formRow">
              <label htmlFor="full-name">Full name</label>
              <input id="full-name" className="input" value={fullName} onChange={(event) => setFullName(event.target.value)} required />
            </div>
          )}
          <div className="formRow">
            <label htmlFor="email">Email</label>
            <input id="email" className="input" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          </div>
          <div className="formRow">
            <label htmlFor="password">Password</label>
            <input id="password" className="input" type="password" minLength={8} value={password} onChange={(event) => setPassword(event.target.value)} required />
          </div>
          <button className="button" type="submit" disabled={loading}>
            {loading ? "Please wait..." : mode === "register" ? "Create Admin" : "Login"}
          </button>
        </form>

        <button
          className="linkButton"
          type="button"
          onClick={() => {
            setError(null);
            setMode(mode === "login" ? "register" : "login");
          }}
        >
          {mode === "login" ? "Create first Admin user" : "Back to login"}
        </button>
      </section>
    </main>
  );
}
