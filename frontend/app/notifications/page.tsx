"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiGet, apiPut, buildQuery } from "@/lib/api";
import type { Notification, NotificationPriority, NotificationStatus, PageResult } from "@/lib/types";
import { Pagination } from "@/components/maintenance/Maintenance";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import { translateNotification, translateStatus } from "@/i18n/translate";

function relatedHref(notification: Notification): string | null {
  const id = notification.entity_id;
  if (!id) return null;
  return {
    ServiceProgramReminder: `/maintenance/programs`,
    ServiceProgram: `/maintenance/programs`,
    WorkOrder: `/work-orders/${id}`,
    VehicleService: `/services/${id}`,
    Inspection: `/inspections/${id}`,
    Vehicle: `/vehicles/${id}`,
    VehicleAssignment: "/vehicle-assignments",
    VehiclePaper: "/papers",
    Driver: "/drivers",
    VehicleReservation: "/reservations"
  }[notification.entity_type ?? ""] ?? null;
}

export default function NotificationsPage() {
  const { t } = useTranslation(["modules", "common"]);
  const { formatDateTime } = useLanguage();
  const [result, setResult] = useState<PageResult<Notification>>({ items: [], page: 1, page_size: 20, total: 0, pages: 0 });
  const [filters, setFilters] = useState({ status: "", priority: "", notification_type: "", from_date: "", to_date: "" });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (page = 1) => {
    setLoading(true); setError(null);
    try {
      setResult(await apiGet<PageResult<Notification>>(`/notifications${buildQuery({ ...filters, page, page_size: 20 })}`));
    } catch (err) { setError(err instanceof Error ? err.message : t("modules:notifications.loadError")); }
    finally { setLoading(false); }
  }, [filters]);

  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function transition(id: number, action: "read" | "resolve" | "dismiss") {
    try { await apiPut(`/notifications/${id}/${action}`, {}); await load(result.page); }
    catch (err) { setError(err instanceof Error ? err.message : t("modules:notifications.updateError")); }
  }

  return <section>
    <div className="header"><div><h1>{t("modules:notifications.title")}</h1><p className="muted">{t("modules:notifications.description")}</p></div><button className="secondaryButton" type="button" onClick={async () => { await apiPut("/notifications/read-all", {}); await load(result.page); }}>{t("modules:notifications.markAllRead")}</button></div>
    {error && <div className="error spaced">{error}</div>}
    <div className="card filtersGrid spaced">
      <select className="select" value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}><option value="">{t("modules:notifications.allStatuses")}</option>{(["Unread", "Read", "Resolved", "Dismissed"] as NotificationStatus[]).map((value) => <option key={value} value={value}>{translateStatus(value)}</option>)}</select>
      <select className="select" value={filters.priority} onChange={(e) => setFilters({ ...filters, priority: e.target.value })}><option value="">{t("modules:notifications.allPriorities")}</option>{(["Low", "Medium", "High", "Critical"] as NotificationPriority[]).map((value) => <option key={value} value={value}>{translateStatus(value)}</option>)}</select>
      <input className="input" placeholder={t("modules:notifications.typePlaceholder")} value={filters.notification_type} onChange={(e) => setFilters({ ...filters, notification_type: e.target.value })} />
      <button className="button" type="button" onClick={() => void load(1)}>{t("common:actions.applyFilters")}</button>
    </div>
    {loading ? <div className="card">{t("modules:notifications.loading")}</div> : <div className="recordList card">
      {result.items.map((notification) => {
        const href = relatedHref(notification);
        return <div className="recordRow" key={notification.id}>
          <div><div className="recordTitle"><strong>{translateNotification(notification.title_key, notification.message_params, notification.title)}</strong><span className={notification.priority === "Critical" ? "dangerBadge" : notification.priority === "High" ? "warningBadge" : "badge"}>{translateStatus(notification.priority)}</span><span className="badge">{translateStatus(notification.status)}</span></div><p>{translateNotification(notification.message_key, notification.message_params, notification.message)}</p><span className="muted">{formatDateTime(notification.created_at)}</span></div>
          <div className="actions">{href && <Link className="secondaryButton smallButton" href={href}>{t("modules:notifications.openRecord")}</Link>}{notification.status === "Unread" && <button className="secondaryButton smallButton" onClick={() => void transition(notification.id, "read")}>{t("modules:notifications.markRead")}</button>}<button className="secondaryButton smallButton" onClick={() => void transition(notification.id, "resolve")}>{t("common:actions.resolve")}</button><button className="secondaryButton smallButton" onClick={() => void transition(notification.id, "dismiss")}>{t("common:actions.dismiss")}</button></div>
        </div>;
      })}
      {!result.items.length && <div className="maintenanceEmpty muted">{t("modules:notifications.empty")}</div>}
    </div>}
    <Pagination page={result.page} pages={result.pages} total={result.total} onPageChange={(page) => void load(page)} />
  </section>;
}
