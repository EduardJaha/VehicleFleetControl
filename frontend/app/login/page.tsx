"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/lib/auth";
import { LanguageSelector } from "@/components/i18n/LanguageSelector";

export default function LoginPage() {
  const router = useRouter();
  const { login, registerFirstAdmin } = useAuth();
  const { t } = useTranslation(["common", "modules"]);
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
      setError(err instanceof Error ? err.message : t("modules:auth.authenticationFailed"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="loginPage">
      <section className="loginCard">
        <div className="loginLanguage"><LanguageSelector /></div>
        <div>
          <h1>{t("common:appName")}</h1>
          <p className="muted">{mode === "register" ? t("modules:auth.firstAdminDescription") : t("modules:auth.signIn")}</p>
        </div>

        {error && <div className="error">{error}</div>}

        <form className="form fullWidthForm" onSubmit={submit}>
          {mode === "register" && (
            <div className="formRow">
              <label htmlFor="full-name">{t("common:labels.fullName")}</label>
              <input id="full-name" className="input" value={fullName} onChange={(event) => setFullName(event.target.value)} required />
            </div>
          )}
          <div className="formRow">
            <label htmlFor="email">{t("common:labels.email")}</label>
            <input id="email" className="input" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          </div>
          <div className="formRow">
            <label htmlFor="password">{t("common:labels.password")}</label>
            <input id="password" className="input" type="password" minLength={8} value={password} onChange={(event) => setPassword(event.target.value)} required />
          </div>
          <button className="button" type="submit" disabled={loading}>
            {loading ? t("common:states.pleaseWait") : mode === "register" ? t("modules:auth.createAdmin") : t("common:actions.login")}
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
          {mode === "login" ? t("modules:auth.createFirstAdmin") : t("modules:auth.backToLogin")}
        </button>
      </section>
    </main>
  );
}
