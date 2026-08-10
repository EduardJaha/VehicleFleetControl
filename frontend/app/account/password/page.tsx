"use client";

import { FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiPut, setAuthToken } from "@/lib/api";
import type { AuthResponse } from "@/lib/types";

export default function ChangePasswordPage() {
  const { t } = useTranslation(["modules", "common"]);
  const [currentPassword, setCurrentPassword] = useState(""); const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState(""); const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault(); setError("");
    if (newPassword !== confirmPassword) { setError(t("modules:admin.passwordsDoNotMatch")); return; }
    try {
      const result = await apiPut<AuthResponse>("/auth/me/password", { current_password: currentPassword, new_password: newPassword });
      setAuthToken(result.access_token); window.location.assign("/dashboard");
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("modules:admin.passwordChangeFailed")); }
  }
  return <form className="card formGrid" onSubmit={submit}><h1>{t("modules:admin.changePassword")}</h1>{error && <div className="error span2">{error}</div>}<label>{t("modules:admin.currentPassword")}<input className="input" type="password" required value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} /></label><label>{t("modules:admin.newPassword")}<input className="input" type="password" required minLength={8} value={newPassword} onChange={(e) => setNewPassword(e.target.value)} /></label><label>{t("modules:admin.confirmPassword")}<input className="input" type="password" required minLength={8} value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} /></label><div><button className="button" type="submit">{t("modules:admin.changePassword")}</button></div></form>;
}
