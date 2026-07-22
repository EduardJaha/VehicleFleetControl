import i18n from "@/i18n";

export function translateStatus(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  const key = `status.${String(value)}`;
  return i18n.exists(key, { ns: "common" }) ? i18n.t(key, { ns: "common" }) : String(value);
}

export function translateType(value: string | null | undefined): string {
  if (!value) return "-";
  const key = `types.${value}`;
  return i18n.exists(key, { ns: "common" }) ? i18n.t(key, { ns: "common" }) : value;
}

export function translateChecklistItem(value: string): string {
  const key = `checklist.${value}`;
  return i18n.exists(key, { ns: "common" }) ? i18n.t(key, { ns: "common" }) : value;
}

export function translateNotification(
  key: string | null | undefined,
  params: Record<string, unknown> | null | undefined,
  fallback: string
): string {
  if (!key) return fallback;
  const localizedParams = { ...(params ?? {}) };
  for (const name of ["status", "priority"]) {
    if (localizedParams[name] !== null && localizedParams[name] !== undefined) localizedParams[name] = translateStatus(String(localizedParams[name]));
  }
  for (const name of ["service_type", "inspection_type", "source", "document_type", "reservation_type"]) {
    if (localizedParams[name] !== null && localizedParams[name] !== undefined) localizedParams[name] = translateType(String(localizedParams[name]));
  }
  return i18n.exists(key) ? i18n.t(key, localizedParams) : fallback;
}
