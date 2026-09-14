"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";
import { todayInputDate } from "@/lib/format";
import { useAuth } from "@/lib/auth";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import { CreateEntityDialog } from "@/components/ui/CreateEntityDialog";
import { MaintenancePageHeader, MaintenanceStatusBadge, MaintenanceTable } from "@/components/maintenance/Maintenance";
import { PROGRAM_API, emptyCompliance, ProgramComplianceCards, ProgramReminderTable, type Program, type ProgramTask, type ProgramRule, type ProgramCompliance } from "@/components/maintenance/Programs";

type Tab = "programs" | "tasks" | "assignments" | "compliance";
type Values = Record<string, string | number | boolean | null>;
type Option = { id: number; name: string };
type Options = { vehicles: Option[]; brands: string[]; models: { brand: string; model: string }[]; fuel_types: string[]; categories: string[]; locations: Option[]; departments: Option[] };
const emptyOptions: Options = { vehicles: [], brands: [], models: [], fuel_types: [], categories: [], locations: [], departments: [] };
const blankTask: Values = { service_type: "Oil Change", title: "", description: "", km_interval: 10000, month_interval: 12, warning_km: 1000, warning_days: 30, whichever_occurs_first: true, priority: "Medium", auto_create_work_order: false, is_active: true, display_order: 0 };

export default function ProgramsPage() {
  const { t } = useTranslation(["modules", "common"]);
  const { formatNumber, formatDate } = useLanguage();
  const { can, user } = useAuth();
  const canRead = can("maintenance.view"), canWrite = can("maintenance.assign_work_order");
  const text = (key: string) => t(`modules:programs.${key}`);
  const [tab, setTab] = useState<Tab>("programs");
  const [programs, setPrograms] = useState<Program[]>([]);
  const [rules, setRules] = useState<ProgramRule[]>([]);
  const [data, setData] = useState<ProgramCompliance>(emptyCompliance);
  const [options, setOptions] = useState<Options>(emptyOptions);
  const [programId, setProgramId] = useState("");
  const [archived, setArchived] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dialog, setDialog] = useState<{ kind: "program" | "task" | "rule"; id?: number } | null>(null);
  const [values, setValues] = useState<Values>({});
  const [dialogError, setDialogError] = useState<string | null>(null);
  const reload = useCallback(async () => {
    if (!canRead) return;
    setLoading(true);
    try {
      const [p, r, c, o] = await Promise.all([apiGet<Program[]>(`${PROGRAM_API}?include_archived=true`), apiGet<ProgramRule[]>(`${PROGRAM_API}/rules`), apiGet<ProgramCompliance>(`${PROGRAM_API}/compliance`), apiGet<Options>(`${PROGRAM_API}/options`)]);
      setPrograms(p); setRules(r); setData(c); setOptions(o); setError(null);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  }, [canRead]);
  useEffect(() => { void reload(); }, [reload, user]);
  const selectedProgram = programs.find(p => p.id === Number(programId));
  function edit(kind: "program" | "task" | "rule", row?: Program | ProgramTask | ProgramRule) {
    setDialog({ kind, id: row?.id }); setDialogError(null);
    if (kind === "program") {
      const p = row as Program | undefined;
      setValues({ name: p?.name || "", description: p?.description || "", is_active: p?.is_active ?? true });
    } else if (kind === "task") {
      const p = row as ProgramTask | undefined;
      setValues(p ? Object.fromEntries(Object.keys(blankTask).map(k => [k, p[k as keyof ProgramTask]])) : { ...blankTask });
    } else {
      const p = row as ProgramRule | undefined;
      setValues({ program_id: p?.program_id || programId || "", target_type: p?.target_type || "Vehicle", target_value: p?.target_value || "", model: p?.model || "", effective_from: p?.effective_from || todayInputDate(), is_active: p?.is_active ?? true });
    }
  }
  async function save(event: React.FormEvent) {
    event.preventDefault(); if (!dialog || busy) return;
    setBusy(true); setDialogError(null);
    try {
      const payload = { ...values };
      for (const key of ["km_interval", "month_interval", "warning_km", "warning_days", "display_order", "program_id"]) {
        if (key in payload) payload[key] = payload[key] === "" || payload[key] === null ? null : Number(payload[key]);
      }
      if ("model" in payload && !payload.model) payload.model = null;
      const path = dialog.kind === "program" ? PROGRAM_API : dialog.kind === "task" ? `${PROGRAM_API}/${programId}/tasks` : `${PROGRAM_API}/rules`;
      const result = dialog.id ? await apiPut<{ id: number }>(`${path}/${dialog.id}`, payload) : await apiPost<{ id: number }>(path, payload);
      if (dialog.kind === "program") setProgramId(String(result.id));
      setDialog(null); await reload();
    } catch (e) { setDialogError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  async function mutate(path: string, restore = false) {
    setBusy(true); setError(null);
    try { if (restore) await apiPost(path, {}); else await apiDelete(path); await reload(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  function input(key: string, type = "text", required = false) {
    return <label className="supplyField" key={key}>{text(key)}<input className="input" type={type} required={required} min={type === "number" ? key.endsWith("interval") ? 1 : 0 : undefined} value={String(values[key] ?? "")} onChange={e => setValues(v => ({ ...v, [key]: e.target.value }))} /></label>;
  }
  function checkbox(key: string) {
    return <label key={key}><input type="checkbox" checked={Boolean(values[key])} disabled={key === "auto_create_work_order" && !can("maintenance.create_work_order")} onChange={e => setValues(v => ({ ...v, [key]: e.target.checked }))} /> {text(key)}</label>;
  }
  const targetOptions: { value: string; label: string }[] = values.target_type === "Vehicle" ? options.vehicles.map(v => ({ value: String(v.id), label: v.name }))
    : values.target_type === "Location" ? options.locations.map(v => ({ value: String(v.id), label: v.name }))
    : values.target_type === "Department" ? options.departments.map(v => ({ value: String(v.id), label: v.name }))
    : (values.target_type === "BrandModel" ? options.brands : values.target_type === "Category" ? options.categories : options.fuel_types).map(v => ({ value: v, label: v }));
  function targetLabel(rule: ProgramRule) {
    const list = rule.target_type === "Vehicle" ? options.vehicles : rule.target_type === "Location" ? options.locations : rule.target_type === "Department" ? options.departments : [];
    return `${list.find(v => String(v.id) === rule.target_value)?.name || rule.target_value}${rule.model ? ` / ${rule.model}` : ""}`;
  }
  if (!canRead) return <p className="card">{text("noPermission")}</p>;
  return <section>
    <MaintenancePageHeader title={text("heading")} description={text("subtitle")} actions={canWrite && <button className="button" disabled={busy} onClick={() => edit("program")}>{text("addProgram")}</button>} />
    <nav className="vehicleTabs" aria-label={text("heading")}>{(["programs", "tasks", "assignments", "compliance"] as Tab[]).map(key => <button key={key} className={`vehicleTab ${tab === key ? "active" : ""}`} onClick={() => setTab(key)}>{text(key)}</button>)}</nav>
    {error && <p className="error" role="alert">{error}</p>}{loading && <p role="status">{text("loading")}</p>}
    {tab === "programs" && <div className="card spaced"><label><input type="checkbox" checked={archived} onChange={e => setArchived(e.target.checked)} /> {text("includeArchived")}</label>
      <MaintenanceTable><thead><tr>{["name", "description", "tasks", "status", "actions"].map(key => <th key={key}>{text(key)}</th>)}</tr></thead><tbody>{programs.filter(p => archived || !p.archived).map(p => <tr key={p.id}><td><button className="link" onClick={() => { setProgramId(String(p.id)); setTab("tasks"); }}>{p.name}</button></td><td>{p.description || "—"}</td><td>{formatNumber(p.tasks.filter(task => task.is_active).length)}</td><td><MaintenanceStatusBadge status={p.archived ? "Archived" : p.is_active ? "Active" : "Inactive"} /></td><td>{canWrite && <div className="actions"><button className="secondaryButton" disabled={busy || p.archived} onClick={() => edit("program", p)}>{text("edit")}</button><button className="secondaryButton" disabled={busy} onClick={() => void mutate(`${PROGRAM_API}/${p.id}${p.archived ? "/restore" : ""}`, p.archived)}>{text(p.archived ? "restore" : "archive")}</button></div>}</td></tr>)}</tbody></MaintenanceTable>
      {!programs.length && !loading && <p>{text("emptyPrograms")}</p>}
    </div>}
    {tab === "tasks" && <section className="card spaced"><div className="actions"><label className="supplyField">{text("program")}<select className="select" value={programId} onChange={e => setProgramId(e.target.value)}><option value="">{text("selectProgram")}</option>{programs.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>{canWrite && <button className="button" disabled={!selectedProgram || selectedProgram.archived || busy} onClick={() => edit("task")}>{text("addTask")}</button>}</div>
      <MaintenanceTable><thead><tr>{["title", "service_type", "interval", "warnings", "priority", "auto_create_work_order", "status", "actions"].map(key => <th key={key}>{text(key)}</th>)}</tr></thead><tbody>{selectedProgram?.tasks.map(task => <tr key={task.id}><td>{task.title}</td><td>{task.service_type}</td><td>{task.km_interval ? `${formatNumber(task.km_interval)} km` : ""}{task.km_interval && task.month_interval ? ` ${text(task.whichever_occurs_first ? "or" : "and")} ` : ""}{task.month_interval ? `${formatNumber(task.month_interval)} ${text("months")}` : ""}</td><td>{task.warning_km != null ? `${formatNumber(task.warning_km)} km` : "—"} / {task.warning_days != null ? `${formatNumber(task.warning_days)} ${text("days")}` : "—"}</td><td>{t(`common:status.${task.priority}`)}</td><td>{text(task.auto_create_work_order ? "yes" : "no")}</td><td><MaintenanceStatusBadge status={task.is_active ? "Active" : "Inactive"} /></td><td>{canWrite && !selectedProgram.archived && <div className="actions"><button className="secondaryButton" disabled={busy} onClick={() => edit("task", task)}>{text("edit")}</button>{task.is_active && <button className="secondaryButton" disabled={busy} onClick={() => void mutate(`${PROGRAM_API}/${programId}/tasks/${task.id}`)}>{text("deactivate")}</button>}</div>}</td></tr>)}</tbody></MaintenanceTable>
      {!selectedProgram?.tasks.length && <p>{text("emptyTasks")}</p>}
    </section>}
    {tab === "assignments" && <section className="card spaced"><p>{text("precedence")}</p><p className="muted">{text("departmentHelp")}</p>{canWrite && <button className="button" disabled={busy} onClick={() => edit("rule")}>{text("addRule")}</button>}
      <MaintenanceTable><thead><tr>{["program", "target_type", "target_value", "effective_from", "status", "actions"].map(key => <th key={key}>{text(key)}</th>)}</tr></thead><tbody>{rules.map(rule => <tr key={rule.id}><td>{programs.find(p => p.id === rule.program_id)?.name}</td><td>{text(rule.target_type)}</td><td>{targetLabel(rule)}</td><td>{formatDate(rule.effective_from)}</td><td><MaintenanceStatusBadge status={rule.is_active ? "Active" : "Inactive"} /></td><td>{canWrite && <div className="actions"><button className="secondaryButton" disabled={busy} onClick={() => edit("rule", rule)}>{text("edit")}</button>{rule.is_active && <button className="secondaryButton" disabled={busy} onClick={() => void mutate(`${PROGRAM_API}/rules/${rule.id}`)}>{text("deactivate")}</button>}</div>}</td></tr>)}</tbody></MaintenanceTable>
      <h2>{text("governingAssignments")}</h2><MaintenanceTable><thead><tr><th>{text("vehicle")}</th><th>{text("program")}</th></tr></thead><tbody>{data.vehicles.map(v => <tr key={v.vehicle_id}><td><Link className="link" href={`/vehicles/${v.vehicle_id}`}>{v.license_plate}</Link></td><td>{v.program_name || text("noProgram")}</td></tr>)}</tbody></MaintenanceTable>
    </section>}
    {tab === "compliance" && <section className="card spaced">{canWrite && <button className="secondaryButton" disabled={busy} onClick={() => void mutate(`${PROGRAM_API}/synchronize`, true)}>{text("synchronize")}</button>}<ProgramComplianceCards data={data} /><ProgramReminderTable items={data.items} /></section>}
    <CreateEntityDialog open={Boolean(dialog)} title={text(dialog?.kind === "program" ? "program" : dialog?.kind === "task" ? "task" : "rule")} busy={busy} onClose={() => setDialog(null)}>
      <form className="form" onSubmit={save}>{dialogError && <p className="error" role="alert">{dialogError}</p>}<div className="formGrid">
        {dialog?.kind === "program" && <>{input("name", "text", true)}{input("description")}{checkbox("is_active")}</>}
        {dialog?.kind === "task" && <>{input("title", "text", true)}{input("service_type", "text", true)}{input("description")}{["km_interval", "month_interval", "warning_km", "warning_days", "display_order"].map(key => input(key, "number"))}<label className="supplyField">{text("priority")}<select className="select" value={String(values.priority)} onChange={e => setValues(v => ({ ...v, priority: e.target.value }))}>{["Low", "Medium", "High", "Critical"].map(p => <option key={p} value={p}>{t(`common:status.${p}`)}</option>)}</select></label>{["whichever_occurs_first", "auto_create_work_order", "is_active"].map(checkbox)}<p className="muted">{text("intervalHelp")}</p></>}
        {dialog?.kind === "rule" && <><label className="supplyField">{text("program")}<select className="select" required value={String(values.program_id)} onChange={e => setValues(v => ({ ...v, program_id: e.target.value }))}><option value="">{text("selectProgram")}</option>{programs.filter(p => !p.archived && p.is_active).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label><label className="supplyField">{text("target_type")}<select className="select" value={String(values.target_type)} onChange={e => setValues(v => ({ ...v, target_type: e.target.value, target_value: "", model: "" }))}>{["Vehicle", "BrandModel", "FuelType", "Category", "Location", "Department"].map(key => <option key={key} value={key}>{text(key)}</option>)}</select></label><label className="supplyField">{text("target_value")}<select className="select" required value={String(values.target_value)} onChange={e => setValues(v => ({ ...v, target_value: e.target.value, model: "" }))}><option value="">{text("choose")}</option>{targetOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select></label>{values.target_type === "BrandModel" && <label className="supplyField">{text("model")}<select className="select" value={String(values.model || "")} onChange={e => setValues(v => ({ ...v, model: e.target.value }))}><option value="">{text("allModels")}</option>{Array.from(new Set(options.models.filter(m => m.brand === values.target_value).map(m => m.model))).map(m => <option key={m} value={m}>{m}</option>)}</select></label>}{input("effective_from", "date", true)}{checkbox("is_active")}</>}
      </div><div className="actions"><button className="button" disabled={busy}>{text("save")}</button><button type="button" className="secondaryButton" disabled={busy} onClick={() => setDialog(null)}>{text("cancel")}</button></div></form>
    </CreateEntityDialog>
  </section>;
}
