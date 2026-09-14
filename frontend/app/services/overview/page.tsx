"use client";

import Link from "next/link";
import { useSupplyData, emptyOptions, type Options } from "@/components/supply/shared";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiDownloadFile, apiPost, apiPostForm, apiPut, maintenanceApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { SERVICE_KM_INTERVALS, SERVICE_SOURCES, SERVICE_TYPES } from "@/lib/constants";
import { toApiDate, toInputDate, todayInputDate } from "@/lib/format";
import type { ApiMessage, PageResult, ServiceSource, VehicleServiceOverview } from "@/lib/types";
import { MaintenanceEmptyState, MaintenancePageHeader, MaintenanceTable, Pagination } from "@/components/maintenance/Maintenance";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import { translateType } from "@/i18n/translate";

import { PROGRAM_API, emptyCompliance, type ProgramCompliance } from "@/components/maintenance/Programs";

type FormState = { vendor_id: string; license_plate: string; service_type: string; service_date: string; odometer_km: string; cost: string; labor_cost: string; parts_cost: string; workshop: string; description: string; next_service_date: string; next_service_km_interval: string; source: ServiceSource; work_order_id: string };
type Filters = { search: string; license_plate: string; service_type: string; workshop: string; from_date: string; to_date: string; source: string; has_linked_work_order: string; minimum_cost: string; maximum_cost: string; include_archived: boolean };

function newForm(params?: URLSearchParams): FormState {
  const workOrder = params?.get("work_order_id") ?? "";
  return { vendor_id: "", license_plate: params?.get("license_plate") ?? "", service_type: params?.get("service_type") ?? "General Service", service_date: todayInputDate(), odometer_km: "", cost: "", labor_cost: "", parts_cost: "", workshop: "", description: "", next_service_date: "", next_service_km_interval: "10000", source: workOrder ? "Work Order" : "Manual", work_order_id: workOrder };
}

function serviceForm(service: VehicleServiceOverview): FormState {
  return { vendor_id: String(service.vendor_id ?? ""), license_plate: service.license_plate, service_type: service.service_type, service_date: toInputDate(service.service_date), odometer_km: service.odometer_km ? String(service.odometer_km) : "", cost: service.cost ? String(service.cost) : "", labor_cost: service.labor_cost ? String(service.labor_cost) : "", parts_cost: service.parts_cost ? String(service.parts_cost) : "", workshop: service.workshop ?? "", description: service.description ?? "", next_service_date: toInputDate(service.next_service_date ?? ""), next_service_km_interval: service.next_service_km_interval ? String(service.next_service_km_interval) : "", source: service.source, work_order_id: service.linked_work_order ? String(service.linked_work_order.id) : "" };
}

function payload(form: FormState) {
  return { vendor_id: form.vendor_id ? Number(form.vendor_id) : null, license_plate: form.license_plate, service_type: form.service_type, service_date: toApiDate(form.service_date), odometer_km: form.odometer_km ? Number(form.odometer_km) : null, cost: form.cost ? Number(form.cost) : null, labor_cost: form.labor_cost ? Number(form.labor_cost) : null, parts_cost: form.parts_cost ? Number(form.parts_cost) : null, workshop: form.workshop || null, description: form.description || null, next_service_date: form.next_service_date ? toApiDate(form.next_service_date) : null, next_service_km_interval: form.next_service_km_interval ? Number(form.next_service_km_interval) : null, source: form.source, work_order_id: form.work_order_id ? Number(form.work_order_id) : null };
}

export default function ServiceHistoryPage() {
  const { t } = useTranslation(["common", "modules"]);
  const { formatCurrency, formatDate, formatNumber } = useLanguage();
  const searchParams = useSearchParams();
  const { can, user } = useAuth();
  const canWrite = can("servicesWrite");
  const vendorOptions = useSupplyData<Options>("/supply-options", emptyOptions, canWrite);
  const [result, setResult] = useState<PageResult<VehicleServiceOverview>>({ items: [], page: 1, page_size: 20, total: 0, pages: 0 });
  const [filters, setFilters] = useState<Filters>({ search: searchParams.get("search") ?? "", license_plate: searchParams.get("license_plate") ?? "", service_type: searchParams.get("service_type") ?? "", workshop: searchParams.get("workshop") ?? "", from_date: searchParams.get("from_date") ?? "", to_date: searchParams.get("to_date") ?? "", source: searchParams.get("source") ?? "", has_linked_work_order: searchParams.get("has_linked_work_order") ?? "", minimum_cost: searchParams.get("minimum_cost") ?? "", maximum_cost: searchParams.get("maximum_cost") ?? "", include_archived: searchParams.get("include_archived") === "true" });
  const [form, setForm] = useState<FormState>(() => newForm(searchParams));
  const [useProgram, setUseProgram] = useState(true);
  const programData = useSupplyData<ProgramCompliance>(`${PROGRAM_API}/compliance`, emptyCompliance, canWrite);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [billFile, setBillFile] = useState<File | null>(null);
  const [laterBill, setLaterBill] = useState({ license_plate: "", service_type: "General Service" });
  const [laterBillFile, setLaterBillFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null); const [message, setMessage] = useState<string | null>(null);
  const programTask = programData.data.items.find(r => r.license_plate.replace(/[^a-z0-9]/gi, "").toLowerCase() === form.license_plate.replace(/[^a-z0-9]/gi, "").toLowerCase() && r.service_type.toLowerCase() === form.service_type.toLowerCase());
  const programSchedule = Boolean(programTask && useProgram);
  const serviceTypes = Array.from(new Set([...SERVICE_TYPES, ...programData.data.items.map(r => r.service_type)]));
  const scheduledPayload = () => payload(programSchedule ? { ...form, next_service_date: "", next_service_km_interval: "" } : form);
  const mileageReminder = !programSchedule && ["General Service", "Oil Change"].includes(form.service_type); const dateReminder = !programSchedule && form.service_type === "Tire Change/Control";

  const load = useCallback(async (page = 1, values = filters) => {
    setLoading(true); setError(null);
    try { setResult(await maintenanceApi.getServices({ page, page_size: 20, ...values, from_date: toApiDate(values.from_date), to_date: toApiDate(values.to_date), has_linked_work_order: values.has_linked_work_order === "" ? undefined : values.has_linked_work_order === "true" })); }
    catch (err) { setError(err instanceof Error ? err.message : t("modules:services.loadError")); } finally { setLoading(false); }
  }, [filters, t]);
  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function appendForm(data: FormData) { Object.entries(scheduledPayload()).forEach(([key, value]) => { if (value !== null && value !== "") data.append(key, String(value)); }); }
  async function save(event: React.FormEvent) {
    event.preventDefault(); setError(null); setMessage(null);
    try {
      let response: ApiMessage | VehicleServiceOverview;
      if (editingId) response = await apiPut<VehicleServiceOverview>(`/services/id/${editingId}`, scheduledPayload());
      else if (billFile) { const data = new FormData(); appendForm(data); data.append("file", billFile); response = await apiPostForm<ApiMessage>("/services/register-with-bill", data); }
      else response = await apiPost<ApiMessage>("/services", scheduledPayload());
      setMessage(t("modules:services.saved", { id: response.id ?? editingId, action: t(`modules:services.${editingId ? "updated" : "created"}`) })); setEditingId(null); setUseProgram(true); setForm(newForm()); setBillFile(null); await load(result.page);
    } catch (err) { setError(err instanceof Error ? err.message : t("modules:services.saveError")); }
  }
  async function uploadLater(event: React.FormEvent) { event.preventDefault(); if (!laterBillFile) return setError(t("modules:services.chooseBill")); const data = new FormData(); data.append("license_plate", laterBill.license_plate); data.append("service_type", laterBill.service_type); data.append("bill_file", laterBillFile); try { await apiPostForm<ApiMessage>("/services/upload-bill-later", data); setMessage(t("modules:services.billUploaded")); setLaterBillFile(null); } catch (err) { setError(err instanceof Error ? err.message : t("modules:services.uploadError")); } }
  async function archive(service: VehicleServiceOverview) { if (!confirm(t("modules:services.archiveConfirm", { id: service.id }))) return; try { await apiPut(`/services/id/${service.id}/archive`, {}); setMessage(t("modules:services.archived", { id: service.id })); await load(result.page); } catch (err) { setError(err instanceof Error ? err.message : t("modules:services.archiveError")); } }
  async function restore(service: VehicleServiceOverview) { try { await apiPost(`/services/id/${service.id}/restore`, {}); setMessage(t("modules:services.restored", { id: service.id })); await load(result.page); } catch (err) { setError(err instanceof Error ? err.message : t("modules:services.restoreError")); } }
  function applyFilters() { const query = new URLSearchParams(); Object.entries(filters).forEach(([key, value]) => { if (value) query.set(key, String(value)); }); window.history.replaceState(null, "", `/services/overview${query.size ? `?${query}` : ""}`); void load(1, filters); }

  return <section>
    <MaintenancePageHeader title={t("modules:services.title")} description={t("modules:services.description")} />
    {error && <div className="error spaced">{error}</div>}{message && <div className="success spaced">{message}</div>}
    {canWrite && <div className="grid cols-2 spaced">
      <form className="form card fullWidthForm" onSubmit={save}><h2>{editingId ? t("modules:services.editTitle", { id: editingId }) : t("modules:services.register")}</h2><div className="formGrid">
        <div className="formRow"><label>{t("labels.licencePlate")}</label><input className="input" required value={form.license_plate} onChange={(e) => setForm({ ...form, license_plate: e.target.value })} /></div>
        <div className="formRow"><label>{t("modules:services.serviceType")}</label><select className="select" value={form.service_type} onChange={(e) => setForm({ ...form, service_type: e.target.value })}>{serviceTypes.map((v) => <option key={v} value={v}>{translateType(v)}</option>)}</select></div>
        <div className="formRow"><label>{t("modules:services.serviceDate")}</label><input className="input" type="date" required value={form.service_date} onChange={(e) => setForm({ ...form, service_date: e.target.value })} /></div>
        <div className="formRow"><label>{t("labels.odometer")}</label><input className="input" type="number" required={mileageReminder} value={form.odometer_km} onChange={(e) => setForm({ ...form, odometer_km: e.target.value })} /></div>
        <div className="formRow"><label>{t("labels.source")}</label><select className="select" value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value as ServiceSource })}>{SERVICE_SOURCES.map((v) => <option key={v} value={v}>{translateType(v)}</option>)}</select></div>
        <div className="formRow"><label>{t("modules:services.workOrderId")}</label><input className="input" type="number" value={form.work_order_id} onChange={(e) => setForm({ ...form, work_order_id: e.target.value, source: e.target.value ? "Work Order" : form.source })} /></div>
        <div className="formRow"><label>{t("modules:supply.vendor_id")}</label><select className="select" value={form.vendor_id} onChange={(e) => setForm({ ...form, vendor_id: e.target.value })}><option value="">{t("modules:supply.select")}</option>{vendorOptions.data.vendors.map(v => <option value={v.id} key={v.id}>{v.name}</option>)}</select></div>
        <div className="formRow"><label>{t("labels.workshop")}</label><input className="input" value={form.workshop} onChange={(e) => setForm({ ...form, workshop: e.target.value })} /></div>
        <div className="formRow"><label>{t("modules:services.legacyCost")}</label><input className="input" type="number" step="0.01" value={form.cost} onChange={(e) => setForm({ ...form, cost: e.target.value })} /></div>
        <div className="formRow"><label>{t("modules:services.laborCost")}</label><input className="input" type="number" step="0.01" value={form.labor_cost} onChange={(e) => setForm({ ...form, labor_cost: e.target.value })} /></div>
        <div className="formRow"><label>{t("modules:services.partsCost")}</label><input className="input" type="number" step="0.01" value={form.parts_cost} onChange={(e) => setForm({ ...form, parts_cost: e.target.value })} /></div>
        {programTask && <label><input type="checkbox" checked={useProgram} onChange={e => setUseProgram(e.target.checked)} /> {t("modules:programs.useSchedule")}</label>}
        {programSchedule && <p className="muted">{t("modules:programs.scheduleHelp")}</p>}
        {mileageReminder && <div className="formRow"><label>{t("modules:services.nextInterval")}</label><select className="select" value={form.next_service_km_interval} onChange={(e) => setForm({ ...form, next_service_km_interval: e.target.value })}>{SERVICE_KM_INTERVALS.map((v) => <option key={v} value={v}>{formatNumber(v)} km</option>)}</select></div>}
        {dateReminder && <div className="formRow"><label>{t("modules:services.nextDate")}</label><input className="input" type="date" required value={form.next_service_date} onChange={(e) => setForm({ ...form, next_service_date: e.target.value })} /></div>}
        <div className="formRow span2"><label>{t("labels.description")}</label><textarea className="input textarea" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></div>
        {!editingId && <div className="formRow span2"><label>{t("modules:services.billOptional")}</label><input className="input" type="file" accept=".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/jpeg,image/png,image/webp" onChange={(e) => setBillFile(e.target.files?.[0] ?? null)} /><span className="muted">{t("modules:services.fileHelpSelected", { file: billFile?.name ?? t("labels.none") })}</span></div>}
      </div><div className="actions"><button className="button">{editingId ? t("modules:services.update") : t("modules:services.save")}</button>{editingId && <button className="secondaryButton" type="button" onClick={() => { setEditingId(null); setUseProgram(true); setForm(newForm()); }}>{t("actions.cancel")}</button>}</div></form>
      <form className="form card fullWidthForm" onSubmit={uploadLater}><h2>{t("modules:services.uploadLater")}</h2><div className="formRow"><label>{t("labels.licencePlate")}</label><input className="input" required value={laterBill.license_plate} onChange={(e) => setLaterBill({ ...laterBill, license_plate: e.target.value })} /></div><div className="formRow"><label>{t("modules:services.serviceType")}</label><select className="select" value={laterBill.service_type} onChange={(e) => setLaterBill({ ...laterBill, service_type: e.target.value })}>{serviceTypes.map((v) => <option key={v} value={v}>{translateType(v)}</option>)}</select></div><div className="formRow"><label>{t("modules:services.billFile")}</label><input className="input" type="file" accept=".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/jpeg,image/png,image/webp" required onChange={(e) => setLaterBillFile(e.target.files?.[0] ?? null)} /><span className="muted">{t("modules:services.fileHelp")}</span></div><button className="button">{t("modules:services.uploadBill")}</button></form>
    </div>}
    <div className="card filtersGrid spaced">
      <input className="input" placeholder={t("modules:services.searchPlaceholder")} value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} /><input className="input" placeholder={t("labels.licencePlate")} value={filters.license_plate} onChange={(e) => setFilters({ ...filters, license_plate: e.target.value })} />
      <select className="select" value={filters.service_type} onChange={(e) => setFilters({ ...filters, service_type: e.target.value })}><option value="">{t("modules:services.allTypes")}</option>{serviceTypes.map((v) => <option key={v} value={v}>{translateType(v)}</option>)}</select><input className="input" placeholder={t("labels.workshop")} value={filters.workshop} onChange={(e) => setFilters({ ...filters, workshop: e.target.value })} />
      <input className="input" type="date" value={filters.from_date} onChange={(e) => setFilters({ ...filters, from_date: e.target.value })} /><input className="input" type="date" value={filters.to_date} onChange={(e) => setFilters({ ...filters, to_date: e.target.value })} />
      <select className="select" value={filters.source} onChange={(e) => setFilters({ ...filters, source: e.target.value })}><option value="">{t("modules:services.allSources")}</option>{SERVICE_SOURCES.map((v) => <option key={v} value={v}>{translateType(v)}</option>)}</select><select className="select" value={filters.has_linked_work_order} onChange={(e) => setFilters({ ...filters, has_linked_work_order: e.target.value })}><option value="">{t("modules:services.anyWorkOrder")}</option><option value="true">{t("modules:services.hasWorkOrder")}</option><option value="false">{t("modules:services.noWorkOrder")}</option></select>
      <input className="input" type="number" placeholder={t("modules:services.minimumCost")} value={filters.minimum_cost} onChange={(e) => setFilters({ ...filters, minimum_cost: e.target.value })} /><input className="input" type="number" placeholder={t("modules:services.maximumCost")} value={filters.maximum_cost} onChange={(e) => setFilters({ ...filters, maximum_cost: e.target.value })} />{user?.role === "admin" && <label className="actions"><input type="checkbox" checked={filters.include_archived} onChange={(e) => setFilters({ ...filters, include_archived: e.target.checked })} /> {t("modules:services.includeArchived")}</label>}<button className="button" type="button" onClick={applyFilters}>{t("actions.applyFilters")}</button>
    </div>
      {loading ? <div className="card">{t("modules:services.loading")}</div> : !result.items.length ? <MaintenanceEmptyState>{t("modules:services.empty")}</MaintenanceEmptyState> : <MaintenanceTable><thead><tr><th>{t("modules:services.idVehicle")}</th><th>{t("modules:services.serviceType")}</th><th>{t("modules:services.dateOdometer")}</th><th>{t("labels.workshop")}</th><th>{t("modules:services.costs")}</th><th>{t("labels.source")}</th><th>{t("modules:services.nextService")}</th><th>{t("modules:services.bill")}</th><th>{t("labels.actions")}</th></tr></thead><tbody>{result.items.map((service) => <tr key={service.id}><td><Link className="link" href={`/services/${service.id}`}>#{service.id}</Link><br /><strong>{service.vehicle_name}</strong><br /><span className="muted">{service.license_plate}</span>{service.archived && <><br /><span className="badge">{t("labels.archived")}</span></>}</td><td>{translateType(service.service_type)}<br /><span className="muted">{service.description ?? "-"}</span></td><td>{formatDate(service.service_date)}<br /><span className="muted">{service.odometer_km ? `${formatNumber(service.odometer_km)} km` : "-"}</span></td><td>{service.workshop ?? "-"}</td><td>{formatCurrency(service.total_cost)}<br /><span className="muted">{t("modules:services.laborParts", { labor: formatCurrency(service.labor_cost), parts: formatCurrency(service.parts_cost) })}</span></td><td>{translateType(service.source)}{service.linked_work_order && <><br /><Link className="link" href={`/work-orders/${service.linked_work_order.id}`}>{t("modules:services.workOrder", { id: service.linked_work_order.id })}</Link></>}</td><td>{service.next_service_date ? formatDate(service.next_service_date) : (service.next_service_odometer_km ? `${formatNumber(service.next_service_odometer_km)} km` : "-")}</td><td>{service.bill_file_path ? <button className="linkButton" type="button" onClick={() => void apiDownloadFile(service.bill_file_path!, `service-${service.id}-bill`)}>{t("modules:services.downloadBill")}</button> : "-"}</td><td><div className="actions"><Link className="secondaryButton smallButton" href={`/services/${service.id}`}>{t("actions.view")}</Link>{canWrite && !service.archived && <><button className="secondaryButton smallButton" onClick={() => { setEditingId(service.id); setUseProgram(!service.next_service_date && !service.next_service_km_interval); setForm(serviceForm(service)); window.scrollTo({ top: 0, behavior: "smooth" }); }}>{t("actions.edit")}</button><button className="secondaryButton smallButton" onClick={() => void archive(service)}>{t("actions.archive")}</button></>}{service.archived && user?.role === "admin" && <button className="secondaryButton smallButton" onClick={() => void restore(service)}>{t("actions.restore")}</button>}</div></td></tr>)}</tbody></MaintenanceTable>}
    <Pagination page={result.page} pages={result.pages} total={result.total} onPageChange={(page) => void load(page)} />
  </section>;
}
