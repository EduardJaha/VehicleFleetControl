"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/lib/auth";
import { apiGet, apiPost } from "@/lib/api";
import { downloadInspection, saveAccidentPack, fromInspection, mobileRequest, ownerOf, reserveLocal, saveDraft, type Draft } from "@/lib/mobile/offline";
import { translateStatus } from "@/i18n/translate";
import type { Inspection } from "@/lib/types";
import { toApiDate, todayInputDate } from "@/lib/format";

type Home = { inspections?: {id: number; vehicle_id: number; inspection_type: string; inspection_date: string}[]; driver_id: number | null; vehicles: {id: number; license_plate: string; name: string; odometer_km: number}[];
 assignments: {id: number; vehicle_id: number; reservation_id?: number; status: string}[]; reservations: {id: number; vehicle_id: number; status: number}[];
 orders: {id: number; title: string; status: string; priority: string}[] };
export default function MobileHome() {
 const { user, can } = useAuth(); const { t } = useTranslation("modules"); const tr = (key: string) => t(`mobile.${key}`);
 const router = useRouter(); const [home, setHome] = useState<Home | null>(null); const [vehicle, setVehicle] = useState("");
 const [error, setError] = useState(""); const [busy, setBusy] = useState(false); const [mode, setMode] = useState("");
 const [odometer, setOdometer] = useState(""); const [condition, setCondition] = useState(""); const [description, setDescription] = useState("");
 const [inspectionType, setInspectionType] = useState("Daily"); const [inspectionDate, setInspectionDate] = useState(todayInputDate());
 const load = useCallback(async () => { const data = await apiGet<Home>("/mobile/home"); setHome(data); setVehicle(v => v || String(data.vehicles[0]?.id || "")); }, []);
 useEffect(() => { void load().catch(e => setError(e.message)); }, [load]);
 const technician = user?.role === "mechanic" || user?.role === "technician";
 const active = home?.assignments.find(a => a.vehicle_id === Number(vehicle) && ["Active", "Overdue"].includes(a.status));
 async function action(fn: () => Promise<void>) {setBusy(true);setError("");try{await fn();}catch(e){setError(e instanceof Error ? e.message : String(e));}finally{setBusy(false);}}
 async function pack() {
   if(!user || !home?.driver_id) return;
   await reserveLocal(ownerOf(user)); saveAccidentPack({owner: ownerOf(user), vehicle_id: Number(vehicle), driver_id: home.driver_id, label: home.vehicles.find(v => v.id === Number(vehicle))?.license_plate || vehicle});
 }
 async function prepare() {
   if(!user) return; const owner = ownerOf(user); await reserveLocal(owner);
   if(can("accidents.report")) await pack();
   const key = crypto.randomUUID();
   // Keep the operation key through network ambiguity so repeating download cannot duplicate a reservation.
   const storageKey = `vfc-prepare-${owner.company_id}-${owner.user_id}-${vehicle}-${inspectionType}-${inspectionDate}`;
   const operationKey = sessionStorage.getItem(storageKey) || key; sessionStorage.setItem(storageKey, operationKey);
   const record = await mobileRequest<Inspection>("/mobile/sync", { ...owner, key: operationKey, kind: "prepare",
     payload: { vehicle_id: Number(vehicle), driver_id: home?.driver_id, inspection_type: inspectionType, inspection_date: toApiDate(inspectionDate) } });
   await saveDraft(fromInspection(record, owner, operationKey)); sessionStorage.removeItem(storageKey); router.push("/mobile/offline");
 }
 async function accident() {
   if(!user || !home?.driver_id) return; const owner = ownerOf(user); await reserveLocal(owner);
   const now = new Date(); const local = new Date(now.getTime()-now.getTimezoneOffset()*60000).toISOString().slice(0,16);
   const draft: Draft = { id: crypto.randomUUID(), owner, kind: "accident", status: "Local Draft", photos: [], updated: Date.now(), attempts: 0,
     label: home.vehicles.find(v => v.id === Number(vehicle))?.license_plate || vehicle,
     payload: {vehicle_id: Number(vehicle), driver_id: home.driver_id, accident_datetime: now.toISOString(), local_datetime: local,
       location: "", description: "", severity: "Minor", vehicle_available_after_accident: false} };
   await saveDraft(draft); router.push("/mobile/offline");
 }
 async function submit(e: React.FormEvent) {
   e.preventDefault(); await action(async () => {
     if(mode === "issue") await apiPost("/mobile/issues", {vehicle_id: Number(vehicle), description});
     else if(mode === "return" && active) await apiPost(`/mobile/assignments/${active.id}/return`, {return_datetime: new Date().toISOString(), ending_odometer_km: Number(odometer), vehicle_condition: condition, new_damage: description || null});
     else await apiPost("/mobile/check-out", {assignment_id: home?.assignments.find(a => a.vehicle_id === Number(vehicle) && a.status === "Scheduled")?.id, reservation_id: home?.assignments.find(a => a.vehicle_id === Number(vehicle) && a.status === "Scheduled")?.reservation_id, vehicle_id: Number(vehicle), driver_id: home?.driver_id, checkout_datetime: new Date().toISOString(), starting_odometer_km: Number(odometer), vehicle_condition: condition, existing_damage: description || null});
     setMode(""); setDescription(""); await load();
   });
 }
 return <div className="mobileWorkspace">
   <p className="mobileEyebrow">{tr(technician ? "technician" : "driver")}</p><h1>{tr("home")}</h1><p>{user?.full_name}</p>
   {error && <p className="error" role="alert">{error}</p>}
   <Link className="mobileTile accent" href="/mobile/offline"><strong>{tr("offlineWork")}</strong><span>{tr("offlineHint")}</span></Link>
   <p className="muted">{tr("installHint")}</p>
   {!home && !error && <p>{tr("loading")}</p>}
   {home && <>
    {technician ? <>
      <h2>{tr("myOrders")}</h2><div className="mobileStats">{["Critical", "In Progress", "Waiting for Parts"].map(value => <div className="card" key={value}><strong>{home.orders.filter(o => value === "Critical" ? o.priority === value : o.status === value).length}</strong><span>{tr(value === "Critical" ? "criticalOrders" : value === "In Progress" ? "inProgress" : "waitingParts")}</span></div>)}</div>
      {!home.orders.length && <p className="card">{tr("noOrders")}</p>}
      {home.orders.map(order => <section className="card mobileOrder" key={order.id}><h3><Link href={`/work-orders/${order.id}`}>{order.title}</Link></h3><p>{translateStatus(order.status)} · {translateStatus(order.priority)}</p>
        <div className="mobileActions">
          {can("labor.manage") && <><Link href={`/work-orders/${order.id}?tab=Labor`}>{tr("clock")}</Link><Link href={`/work-orders/${order.id}?tab=Labor`}>{tr("addLabor")}</Link></>}
          {can("inventory.manage") && <Link href={`/work-orders/${order.id}?tab=Parts`}>{tr("addPart")}</Link>}
          {can("maintenance.assign_work_order") && <Link href={`/work-orders/${order.id}?tab=Attachments`}>{tr("addPhoto")}</Link>}
          {can("maintenance.complete_work_order") && <Link href={`/work-orders/${order.id}`}>{tr("completeOrder")}</Link>}
        </div></section>)}
    </> : <><h2>{tr("myVehicle")}</h2>{!home.vehicles.length && <p className="card">{tr("noVehicle")}</p>}</>}
    {home.vehicles.length > 0 && <section className="card mobileForm">
      <label>{tr("vehicle")}<select className="select" value={vehicle} onChange={e => {setVehicle(e.target.value);setMode("");}}>{home.vehicles.map(v => <option key={v.id} value={v.id}>{v.license_plate} · {v.name}</option>)}</select></label>
      {!technician && <><h3>{tr("myAssignment")}</h3>{active ? <Link href={`/vehicle-assignments/${active.id}`}>#{active.id} · {translateStatus(active.status)}</Link> : <p>{tr("noActive")}</p>}
      <h3>{tr("myReservation")}</h3>{home.reservations.length ? home.reservations.map(r => <Link key={r.id} href="/reservations">#{r.id}</Link>) : <p>{tr("noReservation")}</p>}
      {can("accidents.report") && home.driver_id && <button className="secondaryButton" disabled={busy} onClick={() => void action(async () => {await pack(); router.push("/mobile/offline");})}>{tr("savePack")}</button>}
      <div className="mobileActions">{can("assignments.self_service") && home.driver_id && <button disabled={busy} onClick={() => {setMode(active ? "return" : "checkout");setOdometer(String(home.vehicles.find(v => v.id === Number(vehicle))?.odometer_km || 0));}}>{tr(active ? "return" : "checkout")}</button>}
      {can("maintenance.report_issue") && <button disabled={busy} onClick={() => setMode("issue")}>{tr("reportIssue")}</button>}
      {can("accidents.report") && home.driver_id && <button disabled={busy} onClick={() => void action(accident)}>{tr("reportAccident")}</button>}</div></>}
      {can("inspections.create") && <><label>{tr("inspectionType")}<select className="select" value={inspectionType} onChange={e => setInspectionType(e.target.value)}>{["Daily", "Before Trip", "Return Inspection"].map(s => <option key={s} value={s}>{t(`mobile.types.${s}`)}</option>)}</select></label>
      <label>{tr("inspectionDate")}<input className="input" type="date" value={inspectionDate} onChange={e => setInspectionDate(e.target.value)} /></label>
      <button className="button" disabled={busy || !inspectionDate} onClick={() => void action(prepare)}>{tr("downloadTemplate")}</button><p className="muted">{tr("prepareHelp")}</p></>}
    </section>}
    {home.inspections?.map(inspection => <section className="card mobileOrder" key={inspection.id}>
      <h3>{tr("inspection")} #{inspection.id}</h3><p>{inspection.inspection_date}</p>
      <button className="button" disabled={busy} onClick={() => void action(async () => {
        if(user) { await downloadInspection(inspection.id, ownerOf(user)); router.push("/mobile/offline"); }
      })}>{tr("downloadTemplate")}</button>
    </section>)}
    {mode && <form className="card mobileForm" onSubmit={submit}><h2>{tr(mode === "issue" ? "reportIssue" : mode)}</h2>
      {mode !== "issue" && <><label>{tr("odometer")}<input className="input" required min={0} type="number" value={odometer} onChange={e => setOdometer(e.target.value)} /></label>
      <label>{tr("condition")}<input className="input" required maxLength={50} value={condition} onChange={e => setCondition(e.target.value)} /></label></>}
      <label>{tr(mode === "issue" ? "description" : "damage")}<textarea className="input" required={mode === "issue"} value={description} onChange={e => setDescription(e.target.value)} /></label>
      <button className="button" disabled={busy}>{tr("submit")}</button><button className="secondaryButton" type="button" onClick={() => setMode("")}>{tr("cancel")}</button></form>}
   </>}
   <div className="mobileGrid">{can("documents.view") && <Link className="mobileTile" href="/compliance/documents">{tr("documents")}</Link>}<Link className="mobileTile" href="/notifications">{tr("notifications")}</Link></div>
 </div>;
}
