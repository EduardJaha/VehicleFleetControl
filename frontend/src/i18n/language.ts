export const LANGUAGE_STORAGE_KEY = "vehicleFleetControl.language";
export const LANGUAGE_CHANGE_EVENT = "vehicleFleetControl:language";

export type LanguageCode = "en" | "sq";

let activeLanguage: LanguageCode = "en";

export function isLanguageCode(value: unknown): value is LanguageCode {
  return value === "en" || value === "sq";
}

export function getStoredLanguage(): LanguageCode | null {
  if (typeof window === "undefined") return null;
  const value = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
  return isLanguageCode(value) ? value : null;
}

export function resolveInitialLanguage(): LanguageCode {
  const stored = getStoredLanguage();
  if (stored) return stored;
  if (typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("sq")) return "sq";
  return "en";
}

export function getActiveLanguage(): LanguageCode {
  return activeLanguage;
}

export function applyLanguage(language: LanguageCode, persist = true): void {
  activeLanguage = language;
  if (typeof document !== "undefined") document.documentElement.lang = language;
  if (typeof window !== "undefined") {
    if (persist) window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
    window.dispatchEvent(new CustomEvent<LanguageCode>(LANGUAGE_CHANGE_EVENT, { detail: language }));
  }
}

export function userLanguageSyncKey(userId: number): string {
  return `${LANGUAGE_STORAGE_KEY}.syncedUser.${userId}`;
}
