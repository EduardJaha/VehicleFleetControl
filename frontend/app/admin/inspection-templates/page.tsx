"use client";
import styles from "./templates.module.css";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { INSPECTION_TYPES } from "@/lib/constants";
import { translateType } from "@/i18n/translate";
import { todayInputDate } from "@/lib/format";
import { Assignment, CATEGORIES, emptyItem, FREQUENCIES, ITEM_FLAGS, Schedule, TARGETS, Template, TemplateItem } from "@/lib/inspection-templates";
import { MaintenancePageHeader, MaintenanceTable } from "@/components/maintenance/Maintenance";

type Header = Pick<Template, "code" | "name" | "description" | "inspection_type" | "is_active">;
type Named = { id: number; name: string };
type Options = { vehicles: Named[]; locations: Named[]; departments: Named[]; vehicle_categories: string[]; fuel_types: string[]; brands: string[]; models: {brand: string; model: string}[] };
const blank = (): Header => ({code: "", name: "", description: "", inspection_type: "Daily", is_active: true});
const newRule = (): Assignment => ({target_type: "Vehicle", target_value: "", model: null, priority: 0, is_active: true});
const newSchedule = (): Schedule => ({frequency: "Daily", start_date: todayInputDate(), interval_days: null, interval_km: null, baseline_odometer_km: null, is_active: true});
const EXAMPLES: [string, Template["inspection_type"]][] = [["daily", "Daily"], ["pre_trip", "Before Trip"], ["post_trip", "After Trip"], ["return", "Return Inspection"], ["weekly", "Weekly"], ["monthly", "Monthly"], ["winter", "General"], ["electric", "General"]];

export default function InspectionTemplatesPage() {
  const { t } = useTranslation(["modules", "common"]);
  const { can } = useAuth();
  const allowed = can("inspection_templates.manage");
  const tr = (key: string) => t(`modules:inspectionTemplates.${key}`);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [options, setOptions] = useState<Options | null>(null);
  const [selected, setSelected] = useState<Template | null>(null);
  const [header, setHeader] = useState<Header>(blank);
  const [copySource, setCopySource] = useState<number | null>(null);
  const [item, setItem] = useState<TemplateItem>(emptyItem);
  const [rules, setRules] = useState<Assignment[]>([]);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [rule, setRule] = useState<Assignment>(newRule);
  const [schedule, setSchedule] = useState<Schedule>(newSchedule);
  const [archived, setArchived] = useState(false);
  const [preview, setPreview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const root = "/inspection-templates";
  const load = useCallback(async () => {
    const [rows, opts] = await Promise.all([apiGet<Template[]>(`${root}?include_archived=${archived}`), apiGet<Options>(`${root}/options`)]);
    setTemplates(rows); setOptions(opts);
  }, [archived]);
  useEffect(() => { if (allowed) void load().catch(e => setError(e.message)); }, [load, allowed]);
  async function open(row: Template) {
    const [fresh, assignments, periods] = await Promise.all([apiGet<Template>(`${root}/${row.id}`), apiGet<Assignment[]>(`${root}/${row.id}/assignments`), apiGet<Schedule[]>(`${root}/${row.id}/schedules`)]);
    setSelected(fresh); setHeader({code: fresh.code, name: fresh.name, description: fresh.description, inspection_type: fresh.inspection_type, is_active: fresh.is_active});
    setRules(assignments); setSchedules(periods); setCopySource(null); setItem(emptyItem()); setRule(newRule()); setSchedule(newSchedule());
  }
  async function run(action: () => Promise<void>) {
    setBusy(true); setError(""); setMessage("");
    try { await action(); await load(); setMessage(tr("saved")); } catch (e) { setError(e instanceof Error ? e.message : tr("error")); } finally { setBusy(false); }
  }
  function reset() { setSelected(null); setHeader(blank()); setCopySource(null); setPreview(false); setItem(emptyItem()); setRules([]); setSchedules([]); }
  async function saveHeader(e: React.FormEvent) {
    e.preventDefault(); await run(async () => {
      const row = copySource ? await apiPost<Template>(`${root}/${copySource}/duplicate`, header) : selected ? await apiPut<Template>(`${root}/${selected.id}`, header) : await apiPost<Template>(root, header);
      await open(row);
    });
  }
  async function move(index: number, direction: number) {
    if (!selected) return;
    const ids = selected.items.map(i => i.id!);
    [ids[index], ids[index + direction]] = [ids[index + direction], ids[index]];
    await run(async () => { const row = await apiPut<Template>(`${root}/${selected.id}/items/reorder`, {item_ids: ids}); setSelected(row); });
  }
  function itemPayload(value: TemplateItem) { return {code: value.code, name: value.name, description: value.description, category: value.category, display_order: value.display_order, ...Object.fromEntries(ITEM_FLAGS.map(flag => [flag, value[flag]]))}; }
  function rulePayload(value: Assignment) { return {target_type: value.target_type, target_value: value.target_value, model: value.model || null, priority: value.priority, is_active: value.is_active}; }
  function schedulePayload(value: Schedule) { return {frequency: value.frequency, start_date: value.start_date, interval_days: value.interval_days, interval_km: value.interval_km, baseline_odometer_km: value.baseline_odometer_km, is_active: value.is_active}; }
  const targetOptions: Named[] = !options ? [] : rule.target_type === "Vehicle" ? options.vehicles : rule.target_type === "Location" ? options.locations : rule.target_type === "Department" ? options.departments : [];
  const targetStrings = !options ? [] : rule.target_type === "Category" ? options.vehicle_categories : rule.target_type === "FuelType" ? options.fuel_types : options.brands;
  const writable = selected && !selected.archived && !copySource;
  if (!allowed) return <div className="card">{tr("denied")}</div>;
  return <section className={styles.page}>
    <MaintenancePageHeader title={tr("title")} description={tr("description")} actions={<button className="button" onClick={reset}>{tr("create")}</button>} />
    {error && <div className="error" role="alert">{error}</div>}{message && <div className="successBanner" role="status">{message}</div>}
    <div className="actions spaced"><label><input type="checkbox" checked={archived} onChange={e => setArchived(e.target.checked)} /> {tr("includeArchived")}</label><button className="secondaryButton" disabled={busy} onClick={() => void run(async () => { await apiPost(`${root}/generate`, {}); })}>{tr("generate")}</button></div>
    <div className="detailGrid spaced">
      <section className="card detailCard"><h2>{tr("templates")}</h2>{templates.length === 0 && <p>{tr("empty")}</p>}
        {templates.map(row => <div key={row.id} className="actions spaced"><button className={selected?.id === row.id ? "button" : "secondaryButton"} disabled={busy} onClick={() => void run(() => open(row))}>{row.name}</button><span className="muted">{row.code} · {row.archived ? tr("archived") : translateType(row.inspection_type)}</span></div>)}
      </section>
      <form className="card detailCard" onSubmit={saveHeader}><h2>{copySource ? tr("duplicate") : selected ? tr("edit") : tr("create")}</h2>
        {!selected && !copySource && <label className="formRow">{tr("examples")}<select className="select" defaultValue="" onChange={e => { const found = EXAMPLES.find(([code]) => code === e.target.value); if (found) setHeader({...blank(), code: found[0].toUpperCase(), name: tr(`examplesList.${found[0]}`), inspection_type: found[1]}); }}><option value="">{tr("choose")}</option>{EXAMPLES.map(([code]) => <option key={code} value={code}>{tr(`examplesList.${code}`)}</option>)}</select></label>}
        <fieldset disabled={busy || !!selected?.archived} style={{border: 0, padding: 0}}>
          <label className="formRow">{tr("code")}<input className="input" required maxLength={80} pattern="[A-Za-z0-9_-]+" value={header.code} onChange={e => setHeader({...header, code: e.target.value})} /></label>
          <label className="formRow">{tr("name")}<input className="input" required maxLength={150} value={header.name} onChange={e => setHeader({...header, name: e.target.value})} /></label>
          <label className="formRow">{tr("details")}<textarea className="input" maxLength={5000} value={header.description || ""} onChange={e => setHeader({...header, description: e.target.value})} /></label>
          <label className="formRow">{tr("type")}<select className="select" value={header.inspection_type} onChange={e => setHeader({...header, inspection_type: e.target.value as Header["inspection_type"]})}>{INSPECTION_TYPES.map(type => <option key={type} value={type}>{translateType(type)}</option>)}</select></label>
          <label><input type="checkbox" checked={header.is_active} onChange={e => setHeader({...header, is_active: e.target.checked})} /> {tr("flags.is_active")}</label>
          <div className="actions spaced"><button className="button">{tr("save")}</button></div>
        </fieldset>
        {selected && <div className="actions spaced"><button className="secondaryButton" type="button" onClick={() => setPreview(!preview)}>{tr("preview")}</button><button className="secondaryButton" type="button" onClick={() => {setCopySource(selected.id); setHeader({...header, code: `${selected.code.slice(0, 70)}_COPY`, name: `${selected.name.slice(0, 130)} (${tr("copy")})`}); setSelected(null);}}>{tr("duplicate")}</button><button className="secondaryButton" type="button" disabled={busy} onClick={() => void run(async () => { const row = selected.archived ? await apiPost<Template>(`${root}/${selected.id}/restore`, {}) : await apiPut<Template>(`${root}/${selected.id}/archive`, {}); await open(row); })}>{selected.archived ? tr("restore") : tr("archive")}</button></div>}
      </form>
    </div>
    {selected && preview && <section className="card detailCard"><h2>{tr("preview")} · {selected.name}</h2><p>{selected.description}</p>{selected.items.filter(i => i.is_active).map(i => <div key={i.id} className="spaced"><strong>{i.name}</strong> · {tr(`categories.${i.category}`)}<p>{i.description}</p><span>{ITEM_FLAGS.filter(f => f !== "is_active" && i[f]).map(f => tr(`flags.${f}`)).join(" · ")}</span></div>)}</section>}
    {writable && <>
      <section className="card detailCard"><h2>{tr("items")}</h2><p className="muted">{tr("snapshotHelp")}</p>
        <MaintenanceTable><colgroup><col style={{width: "21%"}} /><col style={{width: "14%"}} /><col style={{width: "37%"}} /><col style={{width: "28%"}} /></colgroup><thead><tr><th>{tr("name")}</th><th>{tr("category")}</th><th>{tr("rules")}</th><th>{tr("actions")}</th></tr></thead><tbody>{selected.items.map((row, index) => <tr key={row.id}><td>{row.name}<br /><span className="muted">{row.code}</span></td><td>{tr(`categories.${row.category}`)}</td><td>{ITEM_FLAGS.filter(flag => row[flag]).map(flag => tr(`flags.${flag}`)).join(" · ")}</td><td><div className="actions"><button className="secondaryButton" disabled={busy || index === 0} aria-label={tr("moveUp")} onClick={() => void move(index, -1)}>↑</button><button className="secondaryButton" disabled={busy || index === selected.items.length - 1} aria-label={tr("moveDown")} onClick={() => void move(index, 1)}>↓</button><button className="secondaryButton" onClick={() => setItem(row)}>{tr("edit")}</button><button className="dangerButton" disabled={busy} onClick={() => void run(async () => {await apiDelete(`${root}/${selected.id}/items/${row.id}`); await open(selected);})}>{tr("delete")}</button></div></td></tr>)}</tbody></MaintenanceTable>
        <form onSubmit={e => {e.preventDefault(); void run(async () => {const path = `${root}/${selected.id}/items`; if (item.id) await apiPut(`${path}/${item.id}`, itemPayload(item)); else await apiPost(path, {...itemPayload(item), display_order: selected.items.length}); await open(selected);});}}>
          <h3>{item.id ? tr("editItem") : tr("addItem")}</h3><fieldset disabled={busy} className="formGrid" style={{border: 0, padding: 0}}>
            <label className="formRow">{tr("code")}<input className="input" required maxLength={80} pattern="[A-Za-z0-9_-]+" value={item.code} onChange={e => setItem({...item, code: e.target.value})} /></label>
            <label className="formRow">{tr("name")}<input className="input" required maxLength={150} value={item.name} onChange={e => setItem({...item, name: e.target.value})} /></label>
            <label className="formRow">{tr("details")}<textarea className="input" value={item.description || ""} onChange={e => setItem({...item, description: e.target.value})} /></label>
            <label className="formRow">{tr("category")}<select className="select" value={item.category} onChange={e => setItem({...item, category: e.target.value})}>{CATEGORIES.map(c => <option key={c} value={c}>{tr(`categories.${c}`)}</option>)}</select></label>
            {ITEM_FLAGS.map(flag => <label key={flag}><input type="checkbox" checked={item[flag]} onChange={e => setItem({...item, [flag]: e.target.checked})} /> {tr(`flags.${flag}`)}</label>)}
            <div className="actions"><button className="button">{tr("save")}</button><button className="secondaryButton" type="button" onClick={() => setItem(emptyItem())}>{tr("cancel")}</button></div>
          </fieldset>
        </form>
      </section>
      <section className="card detailCard"><h2>{tr("assignments")}</h2><p>{tr("precedence")}</p>
        {rules.map(row => <div className="actions spaced" key={row.id}><span>{tr(`targets.${row.target_type}`)}: {([...(options?.vehicles || []), ...(options?.locations || []), ...(options?.departments || [])].find(v => String(v.id) === row.target_value)?.name && ["Vehicle", "Location", "Department"].includes(row.target_type)) ? (row.target_type === "Vehicle" ? options?.vehicles : row.target_type === "Location" ? options?.locations : options?.departments)?.find(v => String(v.id) === row.target_value)?.name : row.target_value} {row.model} · {row.is_active ? tr("active") : tr("inactive")}</span><button className="secondaryButton" disabled={busy} onClick={() => setRule(row)}>{tr("edit")}</button><button className="secondaryButton" disabled={busy || !row.is_active} onClick={() => void run(async () => {await apiDelete(`${root}/${selected.id}/assignments/${row.id}`); await open(selected);})}>{tr("disable")}</button></div>)}
        <form className="formGrid" onSubmit={e => {e.preventDefault(); void run(async () => {const path = `${root}/${selected.id}/assignments`; if (rule.id) await apiPut(`${path}/${rule.id}`, rulePayload(rule)); else await apiPost(path, rulePayload(rule)); await open(selected);});}}>
          <fieldset className="formGrid" disabled={busy} style={{border: 0, padding: 0, gridColumn: "1 / -1"}}>
          <label className="formRow">{tr("target")}<select className="select" value={rule.target_type} onChange={e => setRule({...rule, target_type: e.target.value, target_value: "", model: null})}>{TARGETS.map(type => <option key={type} value={type}>{tr(`targets.${type}`)}</option>)}</select></label>
          <label className="formRow">{tr("value")}<select className="select" required value={rule.target_value} onChange={e => setRule({...rule, target_value: e.target.value})}><option value="">{tr("choose")}</option>{["Vehicle", "Location", "Department"].includes(rule.target_type) ? targetOptions.map(v => <option key={v.id} value={v.id}>{v.name}</option>) : targetStrings.map(v => <option key={v} value={v}>{v}</option>)}</select></label>
          {rule.target_type === "BrandModel" && <label className="formRow">{tr("model")}<select className="select" value={rule.model || ""} onChange={e => setRule({...rule, model: e.target.value || null})}><option value="">{tr("allModels")}</option>{Array.from(new Set(options?.models.filter(v => v.brand === rule.target_value).map(v => v.model))).map(v => <option key={v}>{v}</option>)}</select></label>}
          <label className="formRow">{tr("priority")}<input className="input" type="number" min={-10000} max={10000} value={rule.priority} onChange={e => setRule({...rule, priority: Number(e.target.value)})} /></label><label><input type="checkbox" checked={rule.is_active} onChange={e => setRule({...rule, is_active: e.target.checked})} /> {tr("active")}</label><div className="actions"><button className="button" disabled={busy}>{tr("save")}</button><button className="secondaryButton" type="button" onClick={() => setRule(newRule())}>{tr("cancel")}</button></div>
          </fieldset>
        </form>
      </section>
      <section className="card detailCard"><h2>{tr("schedules")}</h2><p>{tr("scheduleHelp")}</p>
        {schedules.map(row => <div className="actions spaced" key={row.id}><span>{tr(`frequencies.${row.frequency}`)} · {row.start_date} {row.interval_days || row.interval_km || ""} · {row.is_active ? tr("active") : tr("inactive")}</span><button className="secondaryButton" disabled={busy} onClick={() => setSchedule(row)}>{tr("edit")}</button><button className="secondaryButton" disabled={busy || !row.is_active} onClick={() => void run(async () => {await apiDelete(`${root}/${selected.id}/schedules/${row.id}`); await open(selected);})}>{tr("disable")}</button></div>)}
        <form className="formGrid" onSubmit={e => {e.preventDefault(); void run(async () => {const path = `${root}/${selected.id}/schedules`; if (schedule.id) await apiPut(`${path}/${schedule.id}`, schedulePayload(schedule)); else await apiPost(path, schedulePayload(schedule)); await open(selected);});}}>
          <fieldset className="formGrid" disabled={busy} style={{border: 0, padding: 0, gridColumn: "1 / -1"}}>
          <label className="formRow">{tr("frequency")}<select className="select" value={schedule.frequency} onChange={e => setSchedule({...schedule, frequency: e.target.value, interval_days: null, interval_km: null, baseline_odometer_km: null})}>{FREQUENCIES.map(f => <option key={f} value={f}>{tr(`frequencies.${f}`)}</option>)}</select></label>
          <label className="formRow">{tr("startDate")}<input className="input" type="date" required value={schedule.start_date} onChange={e => setSchedule({...schedule, start_date: e.target.value})} /></label>
          {schedule.frequency === "Every X days" && <label className="formRow">{tr("intervalDays")}<input className="input" type="number" required min={1} max={3660} value={schedule.interval_days ?? ""} onChange={e => setSchedule({...schedule, interval_days: Number(e.target.value)})} /></label>}
          {schedule.frequency === "Mileage" && <><label className="formRow">{tr("intervalKm")}<input className="input" type="number" required min={1} max={1000000} value={schedule.interval_km ?? ""} onChange={e => setSchedule({...schedule, interval_km: Number(e.target.value)})} /></label><label className="formRow">{tr("baselineKm")}<input className="input" type="number" required min={0} value={schedule.baseline_odometer_km ?? ""} onChange={e => setSchedule({...schedule, baseline_odometer_km: Number(e.target.value)})} /></label></>}
          <label><input type="checkbox" checked={schedule.is_active} onChange={e => setSchedule({...schedule, is_active: e.target.checked})} /> {tr("active")}</label><div className="actions"><button className="button" disabled={busy}>{tr("save")}</button><button type="button" className="secondaryButton" onClick={() => setSchedule(newSchedule())}>{tr("cancel")}</button></div>
          </fieldset>
        </form>
      </section>
    </>}
  </section>;
}
