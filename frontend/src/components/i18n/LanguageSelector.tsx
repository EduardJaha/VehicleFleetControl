"use client";

import { useTranslation } from "react-i18next";
import { useLanguage } from "@/components/i18n/LanguageProvider";

export function LanguageSelector({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation("common");
  const { language, setLanguage } = useLanguage();
  return (
    <label className={compact ? "languageSelector compact" : "languageSelector"}>
      <span>{t("language.label")}</span>
      <select
        className="select"
        aria-label={t("language.label")}
        value={language}
        onChange={(event) => setLanguage(event.target.value as "en" | "sq")}
      >
        <option value="en">{t("language.english")}</option>
        <option value="sq">{t("language.albanian")}</option>
      </select>
    </label>
  );
}
