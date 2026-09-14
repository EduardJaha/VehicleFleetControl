"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiGet, apiPost } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import { MaintenanceKpiCard, MaintenanceStatusBadge, MaintenanceTable } from "./Maintenance";

export const PROGRAM_API = "/maintenance/programs";
export type ProgramTask = {
  id: number; program_id: number; service_type: string; title: string; description: string | null;
  km_interval: number | null; month_interval: number | null; whichever_occurs_first: boolean;
  warning_km: number | null; warning_days: number | null; priority: string;
  auto_create_work_order: boolean; is_active: boolean; display_order: number;
};
export type Program = { id: number; name: string; description: string | null; is_active: boolean; archived: boolean; tasks: ProgramTask[] };
export type ProgramRule = { id: number; program_id: number; target_type: string; target_value: string; model: string | null; effective_from: string; is_active: boolean };
export type ProgramReminder = { id: number; vehicle_id: number; title: string; service_type: string; license_plate: string; status: string; due_date: string | null; due_odometer_km: number | null; work_order_id: number | null; whichever_occurs_first: boolean };
export type ProgramCompliance = {
  vehicles_with_program: number; vehicles_without_program: number; tasks_current: number; tasks_due_soon: number;
  tasks_overdue: number; tasks_needing_baseline: number; compliance_percent: number | null; coverage_percent: number | null;
  items: ProgramReminder[];
  vehicles: { vehicle_id: number; license_plate: string; program_name: string | null; assignment: { program_id: number; rule_id: number } | null }[];
};
export const emptyCompliance: ProgramCompliance = { vehicles_with_program: 0, vehicles_without_program: 0, tasks_current: 0, tasks_due_soon: 0, tasks_overdue: 0, tasks_needing_baseline: 0, compliance_percent: null, coverage_percent: null, items: [], vehicles: [] };

export function ProgramReminderTable({ items }: { items: ProgramReminder[] }) {
  const { t } = useTranslation(["modules", "common"]);
  const { formatDate, formatNumber } = useLanguage();
  const text = (key: string) => t(`modules:programs.${key}`);
  const { can } = useAuth();
  if (!items.length) return <p className="muted">{text("emptyTasks")}</p>;
  return <MaintenanceTable><thead><tr>
    {["vehicle", "title", "due_date", "due_odometer_km", "trigger", "status", "work_order"].map(key => <th key={key}>{text(key)}</th>)}
  </tr></thead><tbody>{items.map(row => <tr key={row.id}>
    <td><Link className="link" href={`/vehicles/${row.vehicle_id}`}>{row.license_plate}</Link></td><td>{row.title}</td>
    <td>{row.due_date ? formatDate(row.due_date) : "—"}</td><td>{row.due_odometer_km == null ? "—" : `${formatNumber(row.due_odometer_km)} km`}</td>
    <td>{text(row.whichever_occurs_first ? "first" : "both")}</td><td><MaintenanceStatusBadge status={row.status} /></td>
    <td>{row.work_order_id ? <Link className="link" href={`/work-orders/${row.work_order_id}`}>#{row.work_order_id}</Link> : can("maintenance.assign_work_order") ? <Link className="link" href={`/services/overview?license_plate=${encodeURIComponent(row.license_plate)}&service_type=${encodeURIComponent(row.service_type)}`}>{text("recordService")}</Link> : "—"}</td>
  </tr>)}</tbody></MaintenanceTable>;
}

export function ProgramComplianceCards({ data }: { data: ProgramCompliance }) {
  const { t } = useTranslation("modules");
  return <><div className="kpiGrid spaced">{(["vehicles_with_program", "vehicles_without_program", "tasks_current", "tasks_due_soon", "tasks_overdue", "tasks_needing_baseline", "compliance_percent", "coverage_percent"] as const).map(key =>
    <MaintenanceKpiCard key={key} label={t(`programs.${key}`)} value={data[key] == null ? "—" : key.endsWith("percent") ? `${data[key]}%` : data[key] as number} tone={key === "tasks_overdue" ? "danger" : undefined} />
  )}</div><p className="muted">{t("programs.complianceHelp")}</p></>;
}

export function VehicleProgramPanel({ vehicleId }: { vehicleId?: number }) {
  const { t } = useTranslation("modules");
  const { can, user } = useAuth();
  const [data, setData] = useState<ProgramCompliance>(emptyCompliance);
  const [programs, setPrograms] = useState<Program[]>([]);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const canRead = can("maintenance.view");
  const canWrite = can("maintenance.assign_work_order");
  const reload = useCallback(async () => {
    if (!canRead) return;
    setLoading(true);
    try {
      const [result, available] = await Promise.all([
        apiGet<ProgramCompliance>(`${PROGRAM_API}/compliance${vehicleId ? `?vehicle_id=${vehicleId}` : ""}`),
        vehicleId && canWrite ? apiGet<Program[]>(PROGRAM_API) : Promise.resolve([]),
      ]);
      setData(result); setPrograms(available.filter(p => p.is_active && !p.archived)); setError(null);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  }, [canRead, canWrite, vehicleId]);
  useEffect(() => { void reload(); }, [reload, user]);
  async function assign() {
    if (!vehicleId || !selected) return;
    setBusy(true);
    try { await apiPost(`${PROGRAM_API}/rules`, { program_id: Number(selected), target_type: "Vehicle", target_value: String(vehicleId) }); await reload(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  if (!canRead) return null;
  const overdue = data.items.filter(r => r.status === "Overdue");
  return <section className="card spaced">
    <div className="header"><div><h2>{t(`programs.${vehicleId ? "assignedProgram" : "programReminders"}`)}</h2>
      {vehicleId && <p>{loading ? t("programs.loading") : data.vehicles[0]?.program_name || t("programs.noProgram")}</p>}</div>
      <Link className="secondaryButton" href="/maintenance/programs">{t("programs.manage")}</Link></div>
    {error && <p className="error" role="alert">{error}</p>}
    {vehicleId && canWrite && <div className="actions"><select className="select" aria-label={t("programs.program")} value={selected} onChange={e => setSelected(e.target.value)}><option value="">{t("programs.selectProgram")}</option>{programs.map(p => <option value={p.id} key={p.id}>{p.name}</option>)}</select><button className="button" disabled={busy || !selected} onClick={() => void assign()}>{t("programs.assign")}</button></div>}
    {vehicleId && <><h3>{t("programs.overdueTasks")}</h3><ProgramReminderTable items={overdue} /><h3>{t("programs.nextTasks")}</h3></>}
    {!loading && <ProgramReminderTable items={vehicleId ? data.items.filter(r => r.status !== "Overdue") : data.items} />}
  </section>;
}
