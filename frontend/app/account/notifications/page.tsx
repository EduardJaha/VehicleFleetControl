"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiGet, apiPut } from "@/lib/api";

type Preference = {
  notification_type: string;
  in_app_enabled: boolean;
  email_enabled: boolean;
};

export default function NotificationPreferencesPage() {
  const { t } = useTranslation(["modules", "common"]);
  const [items, setItems] = useState<Preference[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void apiGet<{ items: Preference[] }>("/notifications/preferences")
      .then((result) => setItems(result.items))
      .catch((reason) => setError(reason instanceof Error ? reason.message : t("modules:notificationPreferences.loadError")))
      .finally(() => setLoading(false));
  }, [t]);

  function update(index: number, field: "in_app_enabled" | "email_enabled", value: boolean) {
    setSaved(false);
    setItems((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, [field]: value } : item));
  }

  async function save() {
    setSaving(true);
    setSaved(false);
    setError("");
    try {
      const result = await apiPut<{ items: Preference[] }>("/notifications/preferences", { items });
      setItems(result.items);
      setSaved(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("modules:notificationPreferences.saveError"));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="card">{t("common:states.loading")}</div>;

  return (
    <div>
      <div className="pageHeader">
        <div><h1>{t("modules:notificationPreferences.title")}</h1><p className="muted">{t("modules:notificationPreferences.description")}</p></div>
        <button className="button" type="button" disabled={saving} onClick={() => void save()}>{saving ? t("common:states.saving") : t("common:actions.save")}</button>
      </div>
      {saved && <div className="successBanner" role="status">{t("modules:notificationPreferences.saved")}</div>}
      {error && <div className="errorBanner" role="alert">{error}</div>}
      <div className="card tableWrap">
        <table>
          <thead><tr><th>{t("modules:notificationPreferences.type")}</th><th>{t("modules:notificationPreferences.inApp")}</th><th>{t("modules:notificationPreferences.email")}</th></tr></thead>
          <tbody>{items.map((item, index) => (
            <tr key={item.notification_type}>
              <td>{t(`modules:notificationPreferences.types.${item.notification_type}`, { defaultValue: item.notification_type })}</td>
              <td><input type="checkbox" checked={item.in_app_enabled} aria-label={`${item.notification_type} ${t("modules:notificationPreferences.inApp")}`} onChange={(event) => update(index, "in_app_enabled", event.target.checked)} /></td>
              <td><input type="checkbox" checked={item.email_enabled} aria-label={`${item.notification_type} ${t("modules:notificationPreferences.email")}`} onChange={(event) => update(index, "email_enabled", event.target.checked)} /></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </div>
  );
}
