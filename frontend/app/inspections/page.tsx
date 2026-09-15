"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import { apiGet, apiPost, apiPut, maintenanceApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  DEFAULT_INSPECTION_ITEMS, INSPECTION_ITEM_STATUSES, INSPECTION_OVERALL_STATUSES, INSPECTION_TYPES
} from "@/lib/constants";
import { toApiDate, toInputDate, todayInputDate } from "@/lib/format";
import type {
  Inspection, InspectionItem, InspectionItemStatus, InspectionOverallStatus,
  InspectionPayload, InspectionType, PageResult, Vehicle
} from "@/lib/types";
import {
  MaintenanceEmptyState, MaintenancePageHeader, MaintenanceStatusBadge,
  MaintenanceTable, Pagination
} from "@/components/maintenance/Maintenance";
import { translateChecklistItem, translateStatus, translateType } from "@/i18n/translate";

import type { Template } from "@/lib/inspection-templates";

type FormState = {
  vehicle_id: string;
  vehicle_label: string;
  driver_id: string;
  inspection_type: InspectionType;
  inspection_date: string;
  overall_status: "" | InspectionOverallStatus;
  inspector: string;
  notes: string;
  items: InspectionItem[];
};

type Filters = {
  search: string;
  license_plate: string;
  driver_id: string;
  inspection_type: string;
  overall_status: string;
  from_date: string;
  to_date: string;
  has_failed_items: boolean;
  has_linked_work_order: string;
};

const defaultItems = () => DEFAULT_INSPECTION_ITEMS.map((item_name) => ({
  item_name, status: "Not Checked" as InspectionItemStatus, comment: ""
}));

const newForm = (): FormState => ({
  vehicle_id: "", vehicle_label: "", driver_id: "", inspection_type: "Daily",
  inspection_date: todayInputDate(), overall_status: "", inspector: "", notes: "", items: defaultItems()
});

function toForm(value: Inspection): FormState {
  return {
    vehicle_id: String(value.vehicle_id),
    vehicle_label: `${value.license_plate} — ${value.vehicle_name}`,
    driver_id: value.driver_id ? String(value.driver_id) : "",
    inspection_type: value.inspection_type,
    inspection_date: toInputDate(value.inspection_date),
    overall_status: value.overall_status,
    inspector: value.inspector ?? "",
    notes: value.notes ?? "",
    items: value.items.map((item) => ({ ...item, comment: item.comment ?? "" }))
  };
}

function payload(form: FormState): InspectionPayload {
  return {
    vehicle_id: Number(form.vehicle_id),
    driver_id: form.driver_id ? Number(form.driver_id) : null,
    inspection_type: form.inspection_type,
    inspection_date: toApiDate(form.inspection_date),
    overall_status: form.overall_status || null,
    inspector: form.inspector || null,
    notes: form.notes || null,
    archived: false,
    items: form.items.map(({ item_name, status, comment }) => ({ item_name, status, comment: comment || null }))
  };
}

export default function InspectionsPage() {
  const { formatDate } = useLanguage();
  const params = useSearchParams();
  const router = useRouter();
  const [resolvedTemplate, setResolvedTemplate] = useState<Template | null>(null);
  const [resolving, setResolving] = useState(false);
  const [resolveError, setResolveError] = useState(false);
  const { can } = useAuth();
  const { t } = useTranslation(["modules", "common"]);
  const canCreate = can("inspectionsCreate");
  const canManage = can("inspectionsWrite");
  const [filters, setFilters] = useState<Filters>({
    search: params.get("search") ?? "",
    license_plate: params.get("license_plate") ?? "",
    driver_id: params.get("driver_id") ?? "",
    inspection_type: params.get("inspection_type") ?? "",
    overall_status: params.get("overall_status") ?? "",
    from_date: params.get("from_date") ?? "",
    to_date: params.get("to_date") ?? "",
    has_failed_items: params.get("has_failed_items") === "true",
    has_linked_work_order: params.get("has_linked_work_order") ?? ""
  });
  const [result, setResult] = useState<PageResult<Inspection>>({ items: [], page: 1, page_size: 20, total: 0, pages: 0 });
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [vehiclesLoading, setVehiclesLoading] = useState(true);
  const [vehiclesError, setVehiclesError] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(newForm);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async (page = 1, values = filters) => {
    setLoading(true);
    setError(null);
    try {
      setResult(await maintenanceApi.getInspections({
        page,
        page_size: 20,
        ...values,
        from_date: toApiDate(values.from_date),
        to_date: toApiDate(values.to_date),
        has_failed_items: values.has_failed_items || undefined,
        has_linked_work_order: values.has_linked_work_order === ""
          ? undefined
          : values.has_linked_work_order === "true"
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:inspections.loadError"));
    } finally {
      setLoading(false);
    }
  }, [filters, t]);

  const loadVehicles = useCallback(async () => {
    setVehiclesLoading(true);
    setVehiclesError(null);
    try {
      setVehicles(await apiGet<Vehicle[]>("/vehicles"));
    } catch (err) {
      setVehiclesError(err instanceof Error ? err.message : t("modules:inspections.vehiclesLoadError"));
    } finally {
      setVehiclesLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
    void loadVehicles();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let alive = true;
    if (editingId || !form.vehicle_id) { setResolvedTemplate(null); setResolving(false); return; }
    setResolving(true); setResolveError(false);
    apiGet<Template | null>(`/inspection-templates/resolve?vehicle_id=${form.vehicle_id}&inspection_type=${encodeURIComponent(form.inspection_type)}${form.driver_id ? `&driver_id=${form.driver_id}` : ""}`)
      .then(value => { if (alive) setResolvedTemplate(value); })
      .catch(e => { if (alive) { setError(e.message); setResolveError(true); } })
      .finally(() => { if (alive) setResolving(false); });
    return () => { alive = false; };
  }, [form.vehicle_id, form.inspection_type, form.driver_id, editingId]);

  function updateItem(index: number, patch: Partial<InspectionItem>) {
    setForm((current) => ({
      ...current,
      items: current.items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item)
    }));
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const saved = editingId
        ? await apiPut<Inspection>(`/inspections/${editingId}`, payload(form))
        : await apiPost<Inspection>("/inspections", resolvedTemplate ? {...payload(form), items: [], template_id: resolvedTemplate.id} : payload(form));
      if (saved.template_id) { router.push(`/inspections/${saved.id}`); return; }
      setMessage(t("modules:inspections.saved", {
        id: saved.id,
        action: t(`modules:inspections.${editingId ? "updated" : "created"}`)
      }));
      setEditingId(null);
      setForm(newForm());
      await load(result.page);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:inspections.saveError"));
    }
  }

  async function archive(inspection: Inspection) {
    if (!confirm(t("modules:inspections.archiveConfirm", { id: inspection.id }))) return;
    try {
      await apiPut(`/inspections/${inspection.id}/archive`, {});
      setMessage(t("modules:inspections.archived", { id: inspection.id }));
      await load(result.page);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:inspections.archiveError"));
    }
  }

  function applyFilters() {
    const query = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== "" && value !== false) query.set(key, String(value));
    });
    window.history.replaceState(null, "", `/inspections${query.size ? `?${query}` : ""}`);
    void load(1, filters);
  }

  const formFailed = form.items.filter((item) => item.status === "Fail").length;
  return (
    <section>
      <MaintenancePageHeader title={t("modules:inspections.title")} description={t("modules:inspections.description")} />
      {error && <div className="error spaced">{error}</div>}
      {message && <div className="success spaced">{message}</div>}

      {canCreate && (
        <form className="form card fullWidthForm spaced" onSubmit={save}>
          <h2>{editingId ? `${t("modules:inspections.edit")} #${editingId}` : t("modules:inspections.create")}</h2>
          {vehiclesError && <div className="error">{vehiclesError}</div>}
          {formFailed > 0 && <div className="error">{t("modules:inspections.failedWarning", { count: formFailed })}</div>}
          <div className="formGrid">
            <div className="formRow">
              <label>{t("common:labels.vehicle")}</label>
              <select
                className="select"
                required
                disabled={vehiclesLoading || Boolean(vehiclesError)}
                value={form.vehicle_id}
                onChange={(e) => setForm({ ...form, vehicle_id: e.target.value, vehicle_label: "" })}
              >
                <option value="">
                  {vehiclesLoading
                    ? t("modules:inspections.loadingVehicles")
                    : t("modules:inspections.selectVehicle")}
                </option>
                {form.vehicle_id && !vehicles.some((vehicle) => String(vehicle.id) === form.vehicle_id) && (
                  <option value={form.vehicle_id}>{form.vehicle_label}</option>
                )}
                {vehicles.map((vehicle) => (
                  <option key={vehicle.id} value={vehicle.id}>
                    {vehicle.license_plate} — {vehicle.brand} {vehicle.model}
                  </option>
                ))}
              </select>
            </div>
            <div className="formRow"><label>{t("modules:reports.driverId")}</label><input className="input" type="number" value={form.driver_id} onChange={(e) => setForm({ ...form, driver_id: e.target.value })} /></div>
            <div className="formRow"><label>{t("modules:inspections.inspectionType")}</label><select className="select" value={form.inspection_type} onChange={(e) => setForm({ ...form, inspection_type: e.target.value as InspectionType })}>{INSPECTION_TYPES.map((value) => <option key={value} value={value}>{translateType(value)}</option>)}</select></div>
            <div className="formRow"><label>{t("modules:inspections.inspectionDate")}</label><input className="input" type="date" required value={form.inspection_date} onChange={(e) => setForm({ ...form, inspection_date: e.target.value })} /></div>
            <div className="formRow"><label>{t("modules:inspections.overallStatus")}</label><select className="select" value={form.overall_status} onChange={(e) => setForm({ ...form, overall_status: e.target.value as "" | InspectionOverallStatus })}><option value="">{t("modules:inspections.auto")}</option>{INSPECTION_OVERALL_STATUSES.map((value) => <option key={value} value={value}>{translateStatus(value)}</option>)}</select></div>
            <div className="formRow"><label>{t("modules:inspections.inspector")}</label><input className="input" value={form.inspector} onChange={(e) => setForm({ ...form, inspector: e.target.value })} placeholder={t("modules:inspections.defaultsCurrentUser")} /></div>
            <div className="formRow span2"><label>{t("common:labels.notes")}</label><textarea className="input textarea" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></div>
          </div>
          {resolvedTemplate && <div className="card"><h2>{resolvedTemplate.name}</h2><p>{t("modules:inspectionTemplates.beginHelp")}</p><ol>{resolvedTemplate.items.map(item => <li key={item.id}>{item.name}</li>)}</ol></div>}
          {!resolvedTemplate && <><div className="header">
            <h2>{t("modules:inspections.checklist")}</h2>
            <button className="secondaryButton smallButton" type="button" onClick={() => setForm({ ...form, items: [...form.items, { item_name: "", status: "Not Checked", comment: "" }] })}>{t("modules:inspections.addItem")}</button>
          </div>
          <MaintenanceTable>
            <thead><tr><th>{t("modules:inspections.item")}</th><th>{t("common:labels.status")}</th><th>{t("common:labels.comment")}</th><th /></tr></thead>
            <tbody>{form.items.map((item, index) => (
              <tr key={`${index}-${item.item_name}`}>
                <td><input className="input" required value={item.item_name} onChange={(e) => updateItem(index, { item_name: e.target.value })} /></td>
                <td><select className="select" value={item.status} onChange={(e) => updateItem(index, { status: e.target.value as InspectionItemStatus })}>{INSPECTION_ITEM_STATUSES.map((value) => <option key={value} value={value}>{translateStatus(value)}</option>)}</select></td>
                <td><input className="input" value={item.comment ?? ""} onChange={(e) => updateItem(index, { comment: e.target.value })} /></td>
                <td><button className="dangerButton smallButton" type="button" disabled={form.items.length === 1} onClick={() => setForm({ ...form, items: form.items.filter((_, itemIndex) => itemIndex !== index) })}>{t("modules:inspections.remove")}</button></td>
              </tr>
            ))}</tbody>
          </MaintenanceTable></>}
          <div className="actions">
            <button
              className="button"
              disabled={!form.vehicle_id || vehiclesLoading || Boolean(vehiclesError) || resolving || resolveError}
            >
              {editingId ? t("modules:inspections.update") : resolvedTemplate ? t("modules:inspectionTemplates.begin") : t("modules:inspections.create")}
            </button>
            {editingId && <button className="secondaryButton" type="button" onClick={() => { setEditingId(null); setForm(newForm()); }}>{t("common:actions.cancel")}</button>}
          </div>
        </form>
      )}

      <div className="card filtersGrid spaced">
        <input className="input" placeholder={t("modules:inspections.searchPlaceholder")} value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} />
        <select
          className="select"
          disabled={vehiclesLoading || Boolean(vehiclesError)}
          value={filters.license_plate}
          onChange={(e) => setFilters({ ...filters, license_plate: e.target.value })}
        >
          <option value="">
            {vehiclesLoading
              ? t("modules:inspections.loadingVehicles")
              : t("modules:inspections.allVehicles")}
          </option>
          {vehicles.map((vehicle) => (
            <option key={vehicle.id} value={vehicle.license_plate}>
              {vehicle.license_plate} — {vehicle.brand} {vehicle.model}
            </option>
          ))}
        </select>
        <input className="input" type="number" placeholder={t("modules:reports.driverId")} value={filters.driver_id} onChange={(e) => setFilters({ ...filters, driver_id: e.target.value })} />
        <select className="select" value={filters.inspection_type} onChange={(e) => setFilters({ ...filters, inspection_type: e.target.value })}><option value="">{t("modules:inspections.allTypes")}</option>{INSPECTION_TYPES.map((value) => <option key={value} value={value}>{translateType(value)}</option>)}</select>
        <select className="select" value={filters.overall_status} onChange={(e) => setFilters({ ...filters, overall_status: e.target.value })}><option value="">{t("modules:inspections.allStatuses")}</option>{INSPECTION_OVERALL_STATUSES.map((value) => <option key={value} value={value}>{translateStatus(value)}</option>)}</select>
        <input className="input" type="date" value={filters.from_date} onChange={(e) => setFilters({ ...filters, from_date: e.target.value })} />
        <input className="input" type="date" value={filters.to_date} onChange={(e) => setFilters({ ...filters, to_date: e.target.value })} />
        <select className="select" value={filters.has_linked_work_order} onChange={(e) => setFilters({ ...filters, has_linked_work_order: e.target.value })}><option value="">{t("modules:inspections.anyWorkOrder")}</option><option value="true">{t("modules:inspections.hasWorkOrder")}</option><option value="false">{t("modules:inspections.noWorkOrder")}</option></select>
        <label className="actions"><input type="checkbox" checked={filters.has_failed_items} onChange={(e) => setFilters({ ...filters, has_failed_items: e.target.checked })} /> {t("modules:inspections.hasFailed")}</label>
        <button className="button" onClick={applyFilters}>{t("common:actions.applyFilters")}</button>
      </div>

      {loading ? <div className="card">{t("modules:inspections.loading")}</div> : !result.items.length
        ? <MaintenanceEmptyState>{t("modules:inspections.empty")}</MaintenanceEmptyState>
        : (
          <MaintenanceTable>
            <thead><tr><th>ID / {t("common:labels.vehicle")}</th><th>{t("modules:inspections.driverInspector")}</th><th>{t("modules:inspections.typeDate")}</th><th>{t("common:labels.status")}</th><th>{t("modules:inspections.failedItems")}</th><th>{t("modules:inspections.createdWorkOrder")}</th><th>{t("common:labels.actions")}</th></tr></thead>
            <tbody>{result.items.map((inspection) => {
              const failedItems = inspection.items.filter((item) => item.status === "Fail");
              return (
                <tr key={inspection.id} className={inspection.overall_status === "Failed" ? "criticalRow" : undefined}>
                  <td><Link className="link" href={`/inspections/${inspection.id}`}>#{inspection.id}</Link><br /><strong>{inspection.vehicle_name}</strong><br /><span className="muted">{inspection.license_plate}</span></td>
                  <td>{inspection.driver_name ?? inspection.driver_id ?? "-"}<br /><span className="muted">{inspection.inspector ?? t("modules:inspections.noInspector")}</span></td>
                  <td>{translateType(inspection.inspection_type)}<br /><span className="muted">{formatDate(inspection.inspection_date)}</span></td>
                  <td><MaintenanceStatusBadge status={inspection.overall_status} /></td>
                  <td>{failedItems.length ? <><span className="dangerBadge">{t("modules:inspections.failedCount", { count: failedItems.length })}</span><ul className="failedItems">{failedItems.map((item) => <li key={item.id ?? item.item_name}>{translateChecklistItem(item.item_name)}{item.comment ? `: ${item.comment}` : ""}</li>)}</ul></> : "0"}</td>
                  <td>{inspection.linked_work_order ? <><Link className="link" href={`/work-orders/${inspection.linked_work_order.id}`}>{t("modules:inspections.workOrderCreated", { id: inspection.linked_work_order.id })}</Link><br /><MaintenanceStatusBadge status={inspection.linked_work_order.status} /></> : "-"}</td>
                  <td><div className="actions">
                    <Link className="secondaryButton smallButton" href={`/inspections/${inspection.id}`}>{t("common:actions.view")}</Link>
                    {canManage && <>
                      <button className="secondaryButton smallButton" onClick={() => { if (inspection.template_id) { router.push(`/inspections/${inspection.id}`); return; } setEditingId(inspection.id); setForm(toForm(inspection)); window.scrollTo({ top: 0, behavior: "smooth" }); }}>{t("common:actions.edit")}</button>
                      {failedItems.length > 0 && !inspection.linked_work_order && <Link className="button smallButton" href={`/work-orders?inspection_id=${inspection.id}&license_plate=${encodeURIComponent(inspection.license_plate)}`}>{t("modules:workOrders.create")}</Link>}
                      {inspection.linked_work_order && <Link className="secondaryButton smallButton" href={`/work-orders/${inspection.linked_work_order.id}`}>{t("modules:inspections.viewExisting")}</Link>}
                      <button className="secondaryButton smallButton" onClick={() => void archive(inspection)}>{t("common:actions.archive")}</button>
                    </>}
                  </div></td>
                </tr>
              );
            })}</tbody>
          </MaintenanceTable>
        )}
      <Pagination page={result.page} pages={result.pages} total={result.total} onPageChange={(page) => void load(page)} />
    </section>
  );
}
