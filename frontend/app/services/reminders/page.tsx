"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import { MaintenanceEmptyState, MaintenancePageHeader, MaintenancePriorityBadge, MaintenanceStatusBadge, MaintenanceTable, Pagination } from "@/components/maintenance/Maintenance";
import { translateStatus, translateType } from "@/i18n/translate";
import { apiPut, maintenanceApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { REMINDER_STATUSES, SERVICE_TYPES, WORK_ORDER_PRIORITIES } from "@/lib/constants";
import { toApiDate } from "@/lib/format";
import type { PageResult, ServiceReminder } from "@/lib/types";

type Filters = { search: string; license_plate: string; reminder_type: string; status: string; priority: string; from_date: string; to_date: string; overdue_only: boolean; has_linked_work_order: string };

export default function ServiceRemindersPage() {
  const params = useSearchParams();
  const { t } = useTranslation(["common", "modules"]);
  const { formatDate, formatNumber } = useLanguage();
  const { can } = useAuth();
  const canWrite = can("servicesWrite");
  const highlighted = Number(params.get("reminder_id") ?? 0);
  const [filters, setFilters] = useState<Filters>({ search: params.get("search") ?? "", license_plate: params.get("license_plate") ?? "", reminder_type: params.get("reminder_type") ?? "", status: params.get("status") ?? "", priority: params.get("priority") ?? "", from_date: params.get("from_date") ?? "", to_date: params.get("to_date") ?? "", overdue_only: params.get("overdue_only") === "true", has_linked_work_order: params.get("has_linked_work_order") ?? "" });
  const [result, setResult] = useState<PageResult<ServiceReminder>>({ items: [], page: 1, page_size: 20, total: 0, pages: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async (page = 1, values = filters) => {
    setLoading(true);
    setError(null);
    try {
      setResult(await maintenanceApi.getReminders({ page, page_size: 20, ...values, from_date: toApiDate(values.from_date), to_date: toApiDate(values.to_date), overdue_only: values.overdue_only || undefined, has_linked_work_order: values.has_linked_work_order === "" ? undefined : values.has_linked_work_order === "true" }));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:reminders.loadError"));
    } finally {
      setLoading(false);
    }
  }, [filters, t]);
  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function applyFilters() {
    const query = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => { if (value !== "" && value !== false) query.set(key, String(value)); });
    window.history.replaceState(null, "", `/services/reminders${query.size ? `?${query}` : ""}`);
    void load(1, filters);
  }

  async function setStatus(reminder: ServiceReminder, status: "Resolved" | "Dismissed") {
    try {
      await apiPut(`/services/reminders/${reminder.id}/status`, { status });
      setMessage(t("modules:reminders.updated", { service: translateType(reminder.service_type), status: translateStatus(status).toLocaleLowerCase() }));
      await load(result.page);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:reminders.updateError"));
    }
  }

  return <section>
    <MaintenancePageHeader title={t("modules:reminders.title")} description={t("modules:reminders.description")} actions={<button className="secondaryButton" onClick={() => void load(result.page)}>{t("actions.refresh")}</button>} />
    {error && <div className="error spaced">{error}</div>}{message && <div className="success spaced">{message}</div>}
    <div className="card filtersGrid spaced">
      <input className="input" placeholder={t("modules:reminders.searchPlaceholder")} value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} />
      <input className="input" placeholder={t("labels.licencePlate")} value={filters.license_plate} onChange={(e) => setFilters({ ...filters, license_plate: e.target.value })} />
      <select className="select" value={filters.reminder_type} onChange={(e) => setFilters({ ...filters, reminder_type: e.target.value })}><option value="">{t("modules:reminders.allTypes")}</option>{SERVICE_TYPES.map((v) => <option key={v} value={v}>{translateType(v)}</option>)}</select>
      <select className="select" value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}><option value="">{t("modules:reminders.allStatuses")}</option>{REMINDER_STATUSES.map((v) => <option key={v} value={v}>{translateStatus(v)}</option>)}</select>
      <select className="select" value={filters.priority} onChange={(e) => setFilters({ ...filters, priority: e.target.value })}><option value="">{t("modules:reminders.allPriorities")}</option>{WORK_ORDER_PRIORITIES.map((v) => <option key={v} value={v}>{translateStatus(v)}</option>)}</select>
      <input className="input" type="date" value={filters.from_date} onChange={(e) => setFilters({ ...filters, from_date: e.target.value })} />
      <input className="input" type="date" value={filters.to_date} onChange={(e) => setFilters({ ...filters, to_date: e.target.value })} />
      <select className="select" value={filters.has_linked_work_order} onChange={(e) => setFilters({ ...filters, has_linked_work_order: e.target.value })}><option value="">{t("modules:services.anyWorkOrder")}</option><option value="true">{t("modules:services.hasWorkOrder")}</option><option value="false">{t("modules:services.noWorkOrder")}</option></select>
      <label className="actions"><input type="checkbox" checked={filters.overdue_only} onChange={(e) => setFilters({ ...filters, overdue_only: e.target.checked })} /> {t("modules:reminders.overdueOnly")}</label>
      <button className="button" onClick={applyFilters}>{t("actions.applyFilters")}</button>
    </div>
    {loading ? <div className="card">{t("modules:reminders.loading")}</div> : !result.items.length ? <MaintenanceEmptyState>{t("modules:reminders.empty")}</MaintenanceEmptyState> : <MaintenanceTable><thead><tr><th>{t("labels.vehicle")}</th><th>{t("modules:reminders.reminderService")}</th><th>{t("modules:reminders.due")}</th><th>{t("modules:reminders.remaining")}</th><th>{t("labels.status")}</th><th>{t("labels.priority")}</th><th>{t("modules:reminders.linkedWorkOrder")}</th><th>{t("labels.actions")}</th></tr></thead><tbody>{result.items.map((reminder) => {
      const statusLabel = translateStatus(reminder.status);
      const workOrderTitle = t("modules:reminders.dueTitle", { service: translateType(reminder.service_type) });
      const issue = t("modules:reminders.reportedIssue", { status: statusLabel.toLocaleLowerCase() });
      return <tr key={reminder.id} className={reminder.status === "Overdue" || reminder.id === highlighted ? "overdueRow" : undefined}>
        <td><Link className="link" href={`/vehicles/${reminder.vehicle_id}`}>{reminder.vehicle_name}</Link><br /><span className="muted">{reminder.license_plate} · {t("modules:reminders.currentOdometer", { value: reminder.current_odometer_km !== null && reminder.current_odometer_km !== undefined ? formatNumber(reminder.current_odometer_km) : "-" })}</span></td>
        <td>{translateType(reminder.service_type)}<br /><span className="muted">{t("modules:reminders.lastService", { mode: translateType(reminder.reminder_mode), date: formatDate(reminder.service_date) })}</span></td>
        <td>{reminder.next_service_date ? formatDate(reminder.next_service_date) : "-"}<br /><span className="muted">{reminder.next_service_odometer_km ? `${formatNumber(reminder.next_service_odometer_km)} km` : "-"}</span></td>
        <td>{reminder.days_left !== null && reminder.days_left !== undefined ? t("modules:reminders.days", { count: reminder.days_left }) : "-"}<br /><span className="muted">{reminder.km_left !== null && reminder.km_left !== undefined ? `${formatNumber(reminder.km_left)} km` : "-"}</span></td>
        <td><MaintenanceStatusBadge status={reminder.status} /></td><td><MaintenancePriorityBadge priority={reminder.priority} /></td>
        <td>{reminder.linked_work_order ? <Link className="link" href={`/work-orders/${reminder.linked_work_order.id}`}>{t("modules:services.workOrder", { id: reminder.linked_work_order.id })}</Link> : "-"}</td>
        <td><div className="actions">{reminder.linked_work_order
          ? <Link className="secondaryButton smallButton" href={`/work-orders/${reminder.linked_work_order.id}`}>{t("modules:reminders.viewExisting")}</Link>
          : canWrite && !["Resolved", "Dismissed"].includes(reminder.status) ? <Link className="button smallButton" href={`/work-orders?reminder_service_id=${reminder.id}&license_plate=${encodeURIComponent(reminder.license_plate)}&title=${encodeURIComponent(workOrderTitle)}&reported_issue=${encodeURIComponent(issue)}`}>{t("modules:reminders.createWorkOrder")}</Link> : null}
          {canWrite && !["Resolved", "Dismissed"].includes(reminder.status) && <><button className="secondaryButton smallButton" onClick={() => void setStatus(reminder, "Resolved")}>{t("actions.resolve")}</button><button className="secondaryButton smallButton" onClick={() => void setStatus(reminder, "Dismissed")}>{t("actions.dismiss")}</button></>}</div></td>
      </tr>;
    })}</tbody></MaintenanceTable>}
    <Pagination page={result.page} pages={result.pages} total={result.total} onPageChange={(page) => void load(page)} />
  </section>;
}
