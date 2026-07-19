import type { RegistrationCountryCode } from "@/lib/types";

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
      : "Albania licence plates must use the format AA 123 AA.";
  }
  if (!/^[0-9]{5}[A-Z]{2}$/.test(normalized)) {
    return "Kosovo licence plates must use the format 01-123-AB.";
  }
  const region = Number(normalized.slice(0, 2));
  if (region < 1 || region > 7) return "Kosovo region code must be between 01 and 07.";
  const number = Number(normalized.slice(2, 5));
  if (number < 101 || number > 999) return "Kosovo plate number must be between 101 and 999.";
  if (/[TRVWXY]/.test(normalized.slice(5))) {
    return "The selected Kosovo plate contains a letter that is not allowed for an ordinary plate.";
  }
  return null;
}
