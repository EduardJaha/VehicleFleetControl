import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import enCommon from "@/i18n/locales/en/common.json";
import enNavigation from "@/i18n/locales/en/navigation.json";
import enModules from "@/i18n/locales/en/modules.json";
import enErrors from "@/i18n/locales/en/errors.json";
import sqCommon from "@/i18n/locales/sq/common.json";
import sqNavigation from "@/i18n/locales/sq/navigation.json";
import sqModules from "@/i18n/locales/sq/modules.json";
import sqErrors from "@/i18n/locales/sq/errors.json";

export const resources = {
  en: { common: enCommon, navigation: enNavigation, modules: enModules, errors: enErrors },
  sq: { common: sqCommon, navigation: sqNavigation, modules: sqModules, errors: sqErrors }
} as const;

if (!i18n.isInitialized) {
  void i18n.use(initReactI18next).init({
    resources,
    lng: "en",
    fallbackLng: "en",
    defaultNS: "common",
    ns: ["common", "navigation", "modules", "errors"],
    interpolation: { escapeValue: false },
    returnNull: false,
    saveMissing: process.env.NODE_ENV === "development",
    missingKeyHandler: (_languages, namespace, key) => {
      if (process.env.NODE_ENV === "development") {
        console.warn(`[i18n] Missing translation: ${namespace}:${key}`);
      }
    }
  });
}

export default i18n;
