import type { RegistrationCountryCode } from "@/lib/types";
import i18n from "@/i18n";

export function normalizePlateInput(value: string): string {
  return value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 7);
}

export function formatLicensePlateInput(
  country: RegistrationCountryCode,
  value: string
): string {
  const normalized = normalizePlateInput(value);
  if (country === "AL") {
    const first = normalized.slice(0, 2);
    const number = normalized.slice(2, 5);
    const last = normalized.slice(5, 7);
    return [first, number, last].filter(Boolean).join(" ");
  }
  const region = normalized.slice(0, 2);
  const number = normalized.slice(2, 5);
  const last = normalized.slice(5, 7);
  return [region, number, last].filter(Boolean).join("-");
}

export function validateLicensePlateInput(
  country: RegistrationCountryCode,
  value: string
): string | null {
  const normalized = normalizePlateInput(value);
  if (country === "AL") {
    return /^[A-Z]{2}[0-9]{3}[A-Z]{2}$/.test(normalized)
      ? null
      : i18n.t("modules:vehicles.albaniaPlateFormat");
  }
  if (!/^[0-9]{5}[A-Z]{2}$/.test(normalized)) {
    return i18n.t("modules:vehicles.kosovoPlateFormat");
  }
  const region = Number(normalized.slice(0, 2));
  if (region < 1 || region > 7) return i18n.t("modules:vehicles.kosovoRegionFormat");
  const number = Number(normalized.slice(2, 5));
  if (number < 101 || number > 999) return i18n.t("modules:vehicles.kosovoNumberFormat");
  if (/[TRVWXY]/.test(normalized.slice(5))) {
    return i18n.t("modules:vehicles.kosovoLetterFormat");
  }
  return null;
}
