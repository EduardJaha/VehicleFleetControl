"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { I18nextProvider, useTranslation } from "react-i18next";
import i18n from "@/i18n";
import {
  applyLanguage,
  getActiveLanguage,
  LANGUAGE_CHANGE_EVENT,
  LanguageCode,
  resolveInitialLanguage
} from "@/i18n/language";
import { apiPut, getAuthToken } from "@/lib/api";

const LOCALES: Record<LanguageCode, string> = { en: "en-GB", sq: "sq-AL" };

type LanguageContextValue = {
  language: LanguageCode;
  setLanguage: (language: LanguageCode) => void;
  formatDate: (value: string | Date | null | undefined) => string;
  formatDateTime: (value: string | Date | null | undefined) => string;
  formatNumber: (value: number | string | null | undefined, options?: Intl.NumberFormatOptions) => string;
  formatCurrency: (value: number | string | null | undefined) => string;
};

const LanguageContext = createContext<LanguageContextValue | null>(null);

function asDate(value: string | Date | null | undefined): Date | null {
  if (!value) return null;
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  const canonical = /^(\d{2})-(\d{2})-(\d{4})$/.exec(value);
  const date = canonical
    ? new Date(Number(canonical[3]), Number(canonical[2]) - 1, Number(canonical[1]))
    : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const [language, setLanguageState] = useState<LanguageCode>(getActiveLanguage());

  const changeLanguage = useCallback((next: LanguageCode, persistBackend: boolean) => {
    applyLanguage(next);
    setLanguageState(next);
    void i18n.changeLanguage(next);
    if (persistBackend && getAuthToken()) {
      void apiPut<{ preferred_language: LanguageCode }>("/auth/me/language", { language: next }).catch(() => {
        // The local preference remains usable; API errors are surfaced on the next authenticated request.
      });
    }
  }, []);

  useEffect(() => {
    const initial = resolveInitialLanguage();
    changeLanguage(initial, false);
    const updateTitle = () => {
      const heading = document.querySelector("main h1")?.textContent?.trim();
      document.title = heading ? `${heading} | ${i18n.t("common:appName")}` : i18n.t("common:appName");
    };
    const listener = (event: Event) => {
      const next = (event as CustomEvent<LanguageCode>).detail;
      if (next === "en" || next === "sq") {
        setLanguageState(next);
        void i18n.changeLanguage(next);
        document.documentElement.lang = next;
        window.setTimeout(updateTitle, 0);
      }
    };
    const titleObserver = new MutationObserver(updateTitle);
    titleObserver.observe(document.body, { childList: true, subtree: true, characterData: true });
    updateTitle();
    window.addEventListener(LANGUAGE_CHANGE_EVENT, listener);
    return () => {
      titleObserver.disconnect();
      window.removeEventListener(LANGUAGE_CHANGE_EVENT, listener);
    };
  }, [changeLanguage]);

  const value = useMemo<LanguageContextValue>(() => {
    const locale = LOCALES[language];
    return {
      language,
      setLanguage: (next) => changeLanguage(next, true),
      formatDate(value) {
        const date = asDate(value);
        return date ? new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(date) : "-";
      },
      formatDateTime(value) {
        const date = asDate(value);
        return date ? new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(date) : "-";
      },
      formatNumber(value, options) {
        if (value === null || value === undefined || value === "") return "-";
        const number = Number(value);
        return Number.isFinite(number) ? new Intl.NumberFormat(locale, options).format(number) : "-";
      },
      formatCurrency(value) {
        if (value === null || value === undefined || value === "") return "-";
        const number = Number(value);
        return Number.isFinite(number)
          ? new Intl.NumberFormat(locale, { style: "currency", currency: "EUR" }).format(number)
          : "-";
      }
    };
  }, [changeLanguage, language]);

  return (
    <I18nextProvider i18n={i18n}>
      <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>
    </I18nextProvider>
  );
}

export function useLanguage() {
  const context = useContext(LanguageContext);
  if (!context) throw new Error("useLanguage must be used inside LanguageProvider.");
  return context;
}

export function useAppTranslation(namespace?: "common" | "navigation" | "modules" | "errors") {
  return useTranslation(namespace);
}
