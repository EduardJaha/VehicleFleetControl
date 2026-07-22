"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiPost, apiPut, maintenanceApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { WORK_ORDER_PRIORITIES, WORK_ORDER_SOURCES, WORK_ORDER_STATUSES } from "@/lib/constants";
import { toApiDate, toInputDate, todayInputDate } from "@/lib/format";
import type { PageResult, WorkOrder, WorkOrderPayload, WorkOrderPriority, WorkOrderSource, WorkOrderStatus } from "@/lib/types";
import { MaintenanceEmptyState, MaintenancePageHeader, MaintenancePriorityBadge, MaintenanceStatusBadge, MaintenanceTable, Pagination } from "@/components/maintenance/Maintenance";
import { CompleteWorkOrderDialog } from "@/components/maintenance/CompleteWorkOrderDialog";
import type { WorkOrderCompletionResult } from "@/lib/types";
import { translateStatus, translateType } from "@/i18n/translate";
import { useLanguage } from "@/components/i18n/LanguageProvider";

type FormState = {
  license_plate: string; driver_id: string; inspection_id: string; reminder_service_id: string;
  title: string; description: string; reported_issue: string; source: WorkOrderSource;
  priority: WorkOrderPriority; status: WorkOrderStatus; requested_by: string; assigned_to: string;
  workshop: string; expected_completion_date: string; actual_completion_date: string;
  labor_cost: string; parts_cost: string; completed_odometer_km: string; completion_notes: string; completed_by: string; notes: string;
};

type Filters = { search: string; license_plate: string; status: string; priority: string; source: string; assigned_to: string; workshop: string; from_date: string; to_date: string; overdue_only: boolean; has_linked_service: string; include_archived: boolean };

function initialForm(params?: URLSearchParams): FormState {
  const inspectionId = params?.get("inspection_id") ?? "";
  const reminderId = params?.get("reminder_service_id") ?? "";
  return {
    license_plate: params?.get("license_plate") ?? "", driver_id: "", inspection_id: inspectionId, reminder_service_id: reminderId,
    title: params?.get("title") ?? "", description: "", reported_issue: params?.get("reported_issue") ?? "",
    source: inspectionId ? "Inspection" : reminderId ? "Service Reminder" : "Manual", priority: "Medium", status: "Open",
    requested_by: "", assigned_to: "", workshop: "", expected_completion_date: "", actual_completion_date: "",
    labor_cost: "", parts_cost: "", completed_odometer_km: "", completion_notes: "", completed_by: "", notes: ""
  };
}

function toForm(order: WorkOrder): FormState {
  return {
    license_plate: order.license_plate, driver_id: order.driver_id ? String(order.driver_id) : "",
    inspection_id: order.inspection_id ? String(order.inspection_id) : "", reminder_service_id: order.reminder_service_id ? String(order.reminder_service_id) : "",
    title: order.title, description: order.description ?? "", reported_issue: order.reported_issue ?? "", source: order.source,
    priority: order.priority, status: order.status, requested_by: order.requested_by ?? "", assigned_to: order.assigned_to ?? "", workshop: order.workshop ?? "",
    expected_completion_date: toInputDate(order.expected_completion_date ?? ""), actual_completion_date: toInputDate(order.actual_completion_date ?? ""),
    labor_cost: order.labor_cost ? String(order.labor_cost) : "", parts_cost: order.parts_cost ? String(order.parts_cost) : "",
    completed_odometer_km: order.completed_odometer_km ? String(order.completed_odometer_km) : "", completion_notes: order.completion_notes ?? "",
    completed_by: order.completed_by ?? "", notes: order.notes ?? ""
  };
}

function payload(form: FormState): WorkOrderPayload {
  return {
    license_plate: form.license_plate, driver_id: form.driver_id ? Number(form.driver_id) : null,
    inspection_id: form.inspection_id ? Number(form.inspection_id) : null,
    reminder_service_id: form.reminder_service_id ? Number(form.reminder_service_id) : null,
    title: form.title, description: form.description || null, reported_issue: form.reported_issue || null,
    source: form.source, priority: form.priority, status: form.status, requested_by: form.requested_by || null,
    assigned_to: form.assigned_to || null, workshop: form.workshop || null,
    expected_completion_date: form.expected_completion_date ? toApiDate(form.expected_completion_date) : null,
    actual_completion_date: form.actual_completion_date ? toApiDate(form.actual_completion_date) : null,
    labor_cost: form.labor_cost ? Number(form.labor_cost) : null, parts_cost: form.parts_cost ? Number(form.parts_cost) : null,
    completed_odometer_km: form.completed_odometer_km ? Number(form.completed_odometer_km) : null,
    completion_notes: form.completion_notes || null, completed_by: form.completed_by || null, notes: form.notes || null, archived: false
  };
}

function overdue(order: WorkOrder) {
  return !!order.expected_completion_date && !["Completed", "Cancelled"].includes(order.status) && new Date(toInputDate(order.expected_completion_date)) < new Date(todayInputDate());
}

export default function WorkOrdersPage() {
  const { t } = useTranslation(["modules", "common"]);
  const { formatCurrency, formatDate } = useLanguage();
  const searchParams = useSearchParams();
  const { can, user } = useAuth();
  const canWrite = can("workOrdersWrite");
  const initialFilters = useMemo<Filters>(() => ({
    search: searchParams.get("search") ?? "", license_plate: searchParams.get("license_plate") ?? "", status: searchParams.get("status") ?? "",
    priority: searchParams.get("priority") ?? "", source: searchParams.get("source") ?? "", assigned_to: searchParams.get("assigned_to") ?? "",
    workshop: searchParams.get("workshop") ?? "", from_date: searchParams.get("from_date") ?? "", to_date: searchParams.get("to_date") ?? "",
    overdue_only: searchParams.get("overdue_only") === "true", has_linked_service: searchParams.get("has_linked_service") ?? "",
    include_archived: searchParams.get("include_archived") === "true"
  }), [searchParams]);
  const [result, setResult] = useState<PageResult<WorkOrder>>({ items: [], page: 1, page_size: 20, total: 0, pages: 0 });
  const [filters, setFilters] = useState(initialFilters);
  const [form, setForm] = useState<FormState>(() => initialForm(searchParams));
  const [editingId, setEditingId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [completionOrder, setCompletionOrder] = useState<WorkOrder | null>(null);
  const [completionResult, setCompletionResult] = useState<WorkOrderCompletionResult | null>(null);

  const load = useCallback(async (page = 1, values = filters) => {
    setLoading(true); setError(null);
    try {
      const data = await maintenanceApi.getWorkOrders({
        page, page_size: 20, ...values, from_date: toApiDate(values.from_date), to_date: toApiDate(values.to_date),
        overdue_only: values.overdue_only || undefined,
        has_linked_service: values.has_linked_service === "" ? undefined : values.has_linked_service === "true"
      });
      setResult(data);
    } catch (err) { setError(err instanceof Error ? err.message : t("modules:workOrders.loadError")); }
    finally { setLoading(false); }
  }, [filters, t]);

  useEffect(() => { void load(Number(searchParams.get("page") ?? 1), initialFilters); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function applyFilters() {
    const query = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => { if (value !== "" && value !== false) query.set(key, String(value)); });
    window.history.replaceState(null, "", `/work-orders${query.size ? `?${query}` : ""}`);
    void load(1, filters);
  }

  async function save(event: React.FormEvent) {
    event.preventDefault(); setError(null); setMessage(null);
    try {
      const saved = editingId ? await apiPut<WorkOrder>(`/work-orders/${editingId}`, payload(form)) : await apiPost<WorkOrder>("/work-orders", payload(form));
      setMessage(t("modules:workOrders.saved", { id: saved.id, action: t(`modules:workOrders.${editingId ? "updated" : "created"}`) })); setEditingId(null); setForm(initialForm()); await load(result.page);
    } catch (err) { setError(err instanceof Error ? err.message : t("modules:workOrders.saveError")); }
  }

  async function changeStatus(order: WorkOrder, status: WorkOrderStatus) {
    try {
      await apiPut(`/work-orders/${order.id}/status`, { status, actual_completion_date: status === "Completed" ? (order.actual_completion_date ?? toApiDate(todayInputDate())) : order.actual_completion_date });
      setMessage(t("modules:workOrders.statusChanged", { id: order.id, status: translateStatus(status) })); await load(result.page);
    } catch (err) { setError(err instanceof Error ? err.message : t("modules:workOrders.statusError")); }
  }

  async function archive(order: WorkOrder) {
    if (!confirm(t("modules:workOrders.archiveConfirm", { id: order.id }))) return;
    try { await apiPut(`/work-orders/${order.id}/archive`, {}); setMessage(t("modules:workOrders.archived", { id: order.id })); await load(result.page); }
    catch (err) { setError(err instanceof Error ? err.message : t("modules:workOrders.archiveError")); }
  }

  async function restore(order: WorkOrder) {
    try { await apiPost(`/work-orders/${order.id}/restore`, {}); setMessage(t("modules:workOrders.restored", { id: order.id })); await load(result.page); }
    catch (err) { setError(err instanceof Error ? err.message : t("modules:workOrders.restoreError")); }
  }

  return (
    <section>
      <MaintenancePageHeader title={t("modules:workOrders.title")} description={t("modules:workOrders.description")} />
      {error && <div className="error spaced">{error}</div>}{message && <div className="success spaced">{message}</div>}

      {canWrite && <form className="form card fullWidthForm spaced" onSubmit={save}>
        <h2>{editingId ? `${t("modules:workOrders.edit")} #${editingId}` : t("modules:workOrders.create")}</h2>
        <div className="formGrid">
          <div className="formRow"><label>{t("common:labels.licencePlate")}</label><input className="input" required value={form.license_plate} onChange={(e) => setForm({ ...form, license_plate: e.target.value })} /></div>
          <div className="formRow"><label>{t("common:labels.description")}</label><input className="input" required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></div>
          <div className="formRow"><label>{t("common:labels.source")}</label><select className="select" value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value as WorkOrderSource })}>{WORK_ORDER_SOURCES.map((source) => <option key={source} value={source}>{translateType(source)}</option>)}</select></div>
          <div className="formRow"><label>{t("common:labels.priority")}</label><select className="select" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value as WorkOrderPriority })}>{WORK_ORDER_PRIORITIES.map((value) => <option key={value} value={value}>{translateStatus(value)}</option>)}</select></div>
          <div className="formRow"><label>{t("common:labels.status")}</label><select className="select" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value as WorkOrderStatus })}>{WORK_ORDER_STATUSES.filter((value) => value !== "Completed").map((value) => <option key={value} value={value}>{translateStatus(value)}</option>)}</select></div>
          <div className="formRow"><label>{t("modules:workOrders.inspectionId")}</label><input className="input" type="number" value={form.inspection_id} onChange={(e) => setForm({ ...form, inspection_id: e.target.value, source: e.target.value ? "Inspection" : form.source })} /></div>
          <div className="formRow"><label>{t("modules:workOrders.reminderId")}</label><input className="input" type="number" value={form.reminder_service_id} onChange={(e) => setForm({ ...form, reminder_service_id: e.target.value, source: e.target.value ? "Service Reminder" : form.source })} /></div>
          <div className="formRow"><label>{t("modules:reports.driverId")}</label><input className="input" type="number" value={form.driver_id} onChange={(e) => setForm({ ...form, driver_id: e.target.value })} /></div>
          <div className="formRow"><label>{t("modules:workOrders.requestedBy")}</label><input className="input" value={form.requested_by} onChange={(e) => setForm({ ...form, requested_by: e.target.value })} /></div>
          <div className="formRow"><label>{t("modules:workOrders.assignedPerson")}</label><input className="input" value={form.assigned_to} onChange={(e) => setForm({ ...form, assigned_to: e.target.value })} /></div>
          <div className="formRow"><label>{t("common:labels.workshop")}</label><input className="input" value={form.workshop} onChange={(e) => setForm({ ...form, workshop: e.target.value })} /></div>
          <div className="formRow"><label>{t("modules:workOrders.expectedCompletion")}</label><input className="input" type="date" value={form.expected_completion_date} onChange={(e) => setForm({ ...form, expected_completion_date: e.target.value })} /></div>
          <div className="formRow"><label>{t("modules:workOrders.actualCompletion")}</label><input className="input" type="date" required={form.status === "Completed"} value={form.actual_completion_date} onChange={(e) => setForm({ ...form, actual_completion_date: e.target.value })} /></div>
          <div className="formRow"><label>{t("modules:workOrders.laborCost")}</label><input className="input" type="number" min="0" step="0.01" value={form.labor_cost} onChange={(e) => setForm({ ...form, labor_cost: e.target.value })} /></div>
          <div className="formRow"><label>{t("modules:workOrders.partsCost")}</label><input className="input" type="number" min="0" step="0.01" value={form.parts_cost} onChange={(e) => setForm({ ...form, parts_cost: e.target.value })} /></div>
          <div className="formRow"><label>{t("modules:workOrders.completedOdometer")}</label><input className="input" type="number" min="0" value={form.completed_odometer_km} onChange={(e) => setForm({ ...form, completed_odometer_km: e.target.value })} /></div>
          <div className="formRow"><label>{t("modules:workOrders.completedBy")}</label><input className="input" value={form.completed_by} onChange={(e) => setForm({ ...form, completed_by: e.target.value })} /></div>
          <div className="formRow span2"><label>{t("modules:workOrders.reportedIssue")}</label><textarea className="input textarea" value={form.reported_issue} onChange={(e) => setForm({ ...form, reported_issue: e.target.value })} /></div>
          <div className="formRow span2"><label>{t("common:labels.description")}</label><textarea className="input textarea" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></div>
          <div className="formRow span2"><label>{t("modules:workOrders.completionNotes")}</label><textarea className="input textarea" value={form.completion_notes} onChange={(e) => setForm({ ...form, completion_notes: e.target.value })} /></div>
          <div className="formRow span2"><label>{t("modules:workOrders.internalNotes")}</label><textarea className="input textarea" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></div>
        </div>
        <div className="actions"><button className="button" type="submit">{editingId ? t("modules:workOrders.update") : t("modules:workOrders.create")}</button>{editingId && <button className="secondaryButton" type="button" onClick={() => { setEditingId(null); setForm(initialForm()); }}>{t("common:actions.cancel")}</button>}</div>
      </form>}

      <div className="card filtersGrid spaced">
        <input className="input" placeholder={t("modules:workOrders.searchPlaceholder")} value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} />
        <input className="input" placeholder={t("common:labels.licencePlate")} value={filters.license_plate} onChange={(e) => setFilters({ ...filters, license_plate: e.target.value })} />
        <select className="select" value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}><option value="">{t("modules:workOrders.allStatuses")}</option>{WORK_ORDER_STATUSES.map((v) => <option key={v} value={v}>{translateStatus(v)}</option>)}</select>
        <select className="select" value={filters.priority} onChange={(e) => setFilters({ ...filters, priority: e.target.value })}><option value="">{t("modules:workOrders.allPriorities")}</option>{WORK_ORDER_PRIORITIES.map((v) => <option key={v} value={v}>{translateStatus(v)}</option>)}</select>
        <select className="select" value={filters.source} onChange={(e) => setFilters({ ...filters, source: e.target.value })}><option value="">{t("modules:workOrders.allSources")}</option>{WORK_ORDER_SOURCES.map((v) => <option key={v} value={v}>{translateType(v)}</option>)}</select>
        <input className="input" placeholder={t("modules:workOrders.assignedPerson")} value={filters.assigned_to} onChange={(e) => setFilters({ ...filters, assigned_to: e.target.value })} />
        <input className="input" placeholder={t("common:labels.workshop")} value={filters.workshop} onChange={(e) => setFilters({ ...filters, workshop: e.target.value })} />
        <input className="input" type="date" value={filters.from_date} onChange={(e) => setFilters({ ...filters, from_date: e.target.value })} />
        <input className="input" type="date" value={filters.to_date} onChange={(e) => setFilters({ ...filters, to_date: e.target.value })} />
        <select className="select" value={filters.has_linked_service} onChange={(e) => setFilters({ ...filters, has_linked_service: e.target.value })}><option value="">{t("modules:workOrders.anyService")}</option><option value="true">{t("modules:workOrders.hasService")}</option><option value="false">{t("modules:workOrders.noService")}</option></select>
        <label className="actions"><input type="checkbox" checked={filters.overdue_only} onChange={(e) => setFilters({ ...filters, overdue_only: e.target.checked })} /> {t("modules:workOrders.overdueOnly")}</label>
        {user?.role === "admin" && <label className="actions"><input type="checkbox" checked={filters.include_archived} onChange={(e) => setFilters({ ...filters, include_archived: e.target.checked })} /> {t("modules:workOrders.includeArchived")}</label>}
        <button className="button" type="button" onClick={applyFilters}>{t("common:actions.applyFilters")}</button>
      </div>

      {loading ? <div className="card">{t("modules:workOrders.loading")}</div> : result.items.length === 0 ? <MaintenanceEmptyState>{t("modules:workOrders.empty")}</MaintenanceEmptyState> : <MaintenanceTable>
        <thead><tr><th>{t("modules:workOrders.idVehicle")}</th><th>{t("modules:workOrders.titleIssue")}</th><th>{t("common:labels.source")}</th><th>{t("common:labels.priority")}</th><th>{t("common:labels.status")}</th><th>{t("modules:workOrders.assignedWorkshop")}</th><th>{t("modules:workOrders.completion")}</th><th>{t("common:labels.totalCost")}</th><th>{t("modules:workOrders.linkedService")}</th><th>{t("common:labels.actions")}</th></tr></thead>
        <tbody>{result.items.map((order) => <tr key={order.id} className={order.priority === "Critical" ? "criticalRow" : overdue(order) ? "overdueRow" : undefined}>
          <td><Link className="link" href={`/work-orders/${order.id}`}>#{order.id}</Link><br /><strong>{order.vehicle_name}</strong><br /><span className="muted">{order.license_plate}</span></td>
          <td><strong>{order.title}</strong><br /><span className="muted">{order.reported_issue ?? order.description ?? "-"}</span></td>
          <td>{translateType(order.source)}</td><td><MaintenancePriorityBadge priority={order.priority} /></td><td>{order.archived ? <span className="badge">{t("common:labels.archived")}</span> : <MaintenanceStatusBadge status={order.status} />}{overdue(order) && <><br /><span className="dangerBadge">{translateStatus("Overdue")}</span></>}</td>
          <td>{order.assigned_to ?? order.driver_name ?? "-"}<br /><span className="muted">{order.workshop ?? t("modules:workOrders.noWorkshop")}</span></td>
          <td>{order.expected_completion_date ? formatDate(order.expected_completion_date) : "-"}<br /><span className="muted">{t("modules:workOrders.actual")}: {order.actual_completion_date ? formatDate(order.actual_completion_date) : "-"}</span></td><td>{formatCurrency(order.total_cost)}</td>
          <td>{order.linked_service ? <Link className="link" href={`/services/${order.linked_service.id}`}>{t("navigation:serviceHistory")} #{order.linked_service.id}</Link> : "-"}</td>
          <td><div className="actions"><Link className="secondaryButton smallButton" href={`/work-orders/${order.id}`}>{t("common:actions.view")}</Link>{canWrite && !order.archived && <>
            <button className="secondaryButton smallButton" type="button" onClick={() => { setEditingId(order.id); setForm(toForm(order)); window.scrollTo({ top: 0, behavior: "smooth" }); }}>{t("common:actions.edit")}</button>
            {order.status === "Assigned" && <button className="secondaryButton smallButton" onClick={() => void changeStatus(order, "In Progress")}>{t("modules:workOrders.startWork")}</button>}
            {order.status === "In Progress" && <button className="secondaryButton smallButton" onClick={() => void changeStatus(order, "Waiting for Parts")}>{translateStatus("Waiting for Parts")}</button>}
            {!["Completed", "Cancelled"].includes(order.status) && <button className="button smallButton" type="button" onClick={() => setCompletionOrder(order)}>{t("modules:workOrders.complete")}</button>}
            {["Completed", "Cancelled"].includes(order.status) && <button className="secondaryButton smallButton" onClick={() => void archive(order)}>{t("common:actions.archive")}</button>}
          </>}{order.archived && user?.role === "admin" && <button className="secondaryButton smallButton" type="button" onClick={() => void restore(order)}>{t("common:actions.restore")}</button>}</div></td>
        </tr>)}</tbody>
      </MaintenanceTable>}
      <Pagination page={result.page} pages={result.pages} total={result.total} onPageChange={(page) => void load(page)} />
      {completionResult && <div className="success spaced" role="status">
        {t("modules:workOrders.completedMessage", { id: completionResult.work_order.id })}
        {completionResult.service && <> <Link className="link" href={`/services/${completionResult.service.id}`}>{t("modules:workOrders.linkedService")} #{completionResult.service.id}</Link></>}
      </div>}
      <CompleteWorkOrderDialog
        order={completionOrder}
        open={Boolean(completionOrder)}
        onClose={() => setCompletionOrder(null)}
        onCompleted={async (completed, uploadWarning) => {
          setCompletionResult(completed);
          setMessage(uploadWarning ?? t("modules:workOrders.completedMessage", { id: completed.work_order.id }));
          await load(result.page);
        }}
      />
    </section>
  );
}
