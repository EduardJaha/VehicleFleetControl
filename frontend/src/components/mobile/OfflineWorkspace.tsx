"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { LanguageSelector } from "@/components/i18n/LanguageSelector";
import { useAuth } from "@/lib/auth";
import { accidentPack, newAccident, addPhoto, drafts, localOwner, mobileRequest, ownerOf, removeDraft, saveDraft, sameOwner, synchronize, type Draft, type Owner } from "@/lib/mobile/offline";
import type { Inspection, InspectionItem } from "@/lib/types";
import { translateStatus, translateChecklistItem } from "@/i18n/translate";

export default function OfflineWorkspace() {
  const { t } = useTranslation("modules"); const tr = (key: string) => t(`mobile.${key}`);
  const { user, ready } = useAuth();
  const [owner, setOwner] = useState<Owner | null>(null); const [rows, setRows] = useState<Draft[]>([]);
  const [error, setError] = useState(""); const [progress, setProgress] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const refresh = useCallback(async () => {
    const scope = user ? ownerOf(user) : localOwner(); setOwner(previous => previous && scope && sameOwner(previous, scope) ? previous : scope);
    setRows(scope ? await drafts(scope) : []);
  }, [user]);
  useEffect(() => { void refresh().catch(e => setError(e.message)); const listener = () => void refresh().catch(e => setError(e.message));
    window.addEventListener("mobile:drafts", listener); window.addEventListener("storage", listener);
    return () => { window.removeEventListener("mobile:drafts", listener); window.removeEventListener("storage", listener); }; }, [refresh]);
  const sync = useCallback(async (manual = false) => {
    if (!owner || !user || !sameOwner(owner, ownerOf(user))) return;
    setBusy(true); setError("");
    try { await synchronize(owner, (id, percent) => setProgress(p => ({ ...p, [id]: percent })), manual); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); await refresh(); }
  }, [owner, user, refresh]);
  useEffect(() => { const onOnline = () => void sync(); window.addEventListener("online", onOnline);
    const timer = window.setInterval(onOnline, 30000); void sync();
    return () => { window.removeEventListener("online", onOnline); window.clearInterval(timer); }; }, [sync]);
  return <main className="mobileWorkspace">
    <div className="mobileHeading"><Link className="link" href="/mobile">{tr("home")}</Link><LanguageSelector compact /></div>
    <h1>{tr("offlineWork")}</h1><p>{tr("privacy")}</p>
    {ready && !user && <p className="error"><Link href="/login">{tr("signIn")}</Link></p>}
    {error && <p className="error" role="alert">{error}</p>}
    <button className="button" disabled={busy || !user} onClick={() => void sync(true)}>{busy ? tr("syncing") : tr("sync")}</button>
    {owner && accidentPack(owner) && <button className="secondaryButton" onClick={() => void newAccident(accidentPack(owner)!).catch(e => setError(e.message))}>{tr("newAccident")}</button>}
    {!rows.length && <p className="card">{tr("noDrafts")}</p>}
    {rows.map(draft => <DraftEditor key={draft.id} draft={draft} progress={progress[draft.id] || 0} onError={setError} />)}
  </main>;
}
function DraftEditor({ draft, progress, onError }: { draft: Draft; progress: number; onError: (text: string) => void }) {
  const { t } = useTranslation("modules"); const tr = (key: string) => t(`mobile.${key}`);
  const [local, setLocal] = useState(draft); const [dirty, setDirty] = useState(false); const [busy, setBusy] = useState(false);
  const [server, setServer] = useState<Inspection | null>(null);
  const editable = draft.status === "Local Draft";
  useEffect(() => { if (draft.status !== "Local Draft") { setLocal(draft); setDirty(false); } }, [draft]);
  useEffect(() => { const before = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", before); return () => window.removeEventListener("beforeunload", before); }, [dirty]);
  async function action(fn: () => Promise<void>) { setBusy(true); try { await fn(); } catch (e) { onError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); } }
  function patchItem(index: number, update: Partial<InspectionItem>) {
    setLocal(d => ({ ...d, payload: { ...d.payload, items: (d.payload.items as InspectionItem[]).map((item, i) => i === index ? { ...item, ...update } : item) } })); setDirty(true);
  }
  function patch(field: string, value: unknown) { setLocal(d => ({ ...d, payload: { ...d.payload, [field]: value } })); setDirty(true); }
  async function photo(file: File, itemId?: number) { const next = await addPhoto(local, file, itemId); await saveDraft(next); setLocal(next); setDirty(false); }
  async function save(queue: boolean) { const next: Draft = { ...local, status: queue ? "Pending Sync" : "Local Draft", updated: Date.now() }; await saveDraft(next); setLocal(next); setDirty(false); }
  function exportDraft() {
    // Portable JSON preserves entered results and server photo references, without raw image expansion.
    const blob = new Blob([JSON.stringify({ ...local, photos: local.photos.map(({blob: _blob, ...p}) => p) }, null, 2)], {type: "application/json"});
    const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = `fleet-draft-${local.id}.json`; a.click(); URL.revokeObjectURL(url);
  }
  return <section className="card mobileDraft">
    <div className="mobileHeading"><h2>{draft.label}</h2><span className={`mobileStatus status-${draft.status.replaceAll(" ", "")}`}>{tr(`statuses.${draft.status}`)}</span></div>
    <p>{tr(draft.kind)}{dirty ? ` · ${tr("unsaved")}` : ""}</p>
    {draft.status !== "Synced" && Date.now() - draft.updated > 30 * 86400000 && <p className="error">{tr("ageWarning")}</p>}
    {draft.error && <p className="error" role="alert">{draft.error}</p>}
    {draft.status === "Syncing" && <progress aria-label={tr("uploadProgress")} max={100} value={progress} />}
    {draft.status === "Conflict" && <div className="mobileConflict"><p>{tr("conflictHelp")}</p>
      {draft.kind === "inspection" && <button className="secondaryButton" onClick={() => void action(async () => setServer(await mobileRequest<Inspection>(`/mobile/inspections/${draft.serverId}`)))}>{tr("reviewServer")}</button>}
      {server && <div><h3>{tr("serverVersion")}</h3>{server.items.map(item => <p key={item.id}>{item.item_name}: {translateStatus(item.status)} — {item.comment}</p>)}</div>}
    </div>}
    {draft.status !== "Synced" && <fieldset disabled={!editable || busy}>
      {local.kind === "inspection" ? (local.payload.items as InspectionItem[] || []).map((item, index) => <div className="mobileCheck" key={item.id}>
        <h3>{translateChecklistItem(item.item_name)} {item.item_snapshot?.required && <span aria-label={tr("required")}>*</span>}</h3>
        <p>{item.item_snapshot?.description}</p>
        <label>{tr("result")}<select className="select" value={item.status} onChange={e => patchItem(index, { status: e.target.value as InspectionItem["status"] })}>
          {["Not Checked", "Pass", "Fail"].map(status => <option key={status} value={status}>{translateStatus(status)}</option>)}</select></label>
        <label>{tr("comment")}<textarea className="input" value={item.comment || ""} onChange={e => patchItem(index, { comment: e.target.value })} /></label>
        {item.status === "Fail" && <p className="muted">{item.item_snapshot?.photo_required_on_failure && tr("photoRequired")} {item.item_snapshot?.comment_required_on_failure && tr("commentRequired")}</p>}
        <label>{tr("addPhoto")}<input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" onChange={e => { const f = e.target.files?.[0]; if (f) void action(() => photo(f, item.id)); e.target.value = ""; }} /></label>
        <PhotoList photos={local.photos.filter(p => p.itemId === item.id)} />
      </div>) : <div className="mobileForm">
        <label>{tr("dateTime")}<input className="input" type="datetime-local" value={String(local.payload.local_datetime || "")} onChange={e => {patch("local_datetime", e.target.value); if(e.target.value) patch("accident_datetime", new Date(e.target.value).toISOString());}} /></label>
        <label>{tr("location")}<input className="input" maxLength={500} value={String(local.payload.location || "")} onChange={e => patch("location", e.target.value)} /></label>
        <label>{tr("description")}<textarea className="input" maxLength={5000} value={String(local.payload.description || "")} onChange={e => patch("description", e.target.value)} /></label>
        <label>{tr("severity")}<select className="select" value={String(local.payload.severity)} onChange={e => patch("severity", e.target.value)}>{["Minor", "Moderate", "Severe", "Critical"].map(s => <option key={s} value={s}>{translateStatus(s)}</option>)}</select></label>
        <label><input type="checkbox" checked={Boolean(local.payload.vehicle_available_after_accident)} onChange={e => patch("vehicle_available_after_accident", e.target.checked)} /> {tr("vehicleSafe")}</label>
        <label>{tr("addPhoto")}<input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" onChange={e => { const f = e.target.files?.[0]; if(f) void action(() => photo(f)); e.target.value = ""; }} /></label><PhotoList photos={local.photos} />
      </div>}
    </fieldset>}
    <div className="actions">
      {editable && <><button className="secondaryButton" disabled={busy} onClick={() => void action(() => save(false))}>{tr("saveLocal")}</button>
        <button className="button" disabled={busy || (local.kind === "accident" && (!local.payload.location || !local.payload.description))} onClick={() => void action(() => save(true))}>{tr("queue")}</button></>}
      {draft.status === "Failed" && (draft.kind === "inspection" || !draft.serverId) && <button className="secondaryButton" onClick={() => void action(async () => {const next: Draft = {...draft, status: "Local Draft", error: undefined}; await saveDraft(next); setLocal(next);})}>{tr("editDraft")}</button>}
      {draft.status === "Synced" && <Link className="link" href={draft.kind === "inspection" ? `/inspections/${draft.serverId}` : `/accidents/${draft.serverId}`}>{tr("openRecord")}</Link>}
      {draft.status !== "Syncing" && <><button className="secondaryButton" onClick={exportDraft}>{tr("export")}</button>
        <button className="secondaryButton" onClick={() => { if(window.confirm(tr("deleteConfirm"))) void action(() => removeDraft(draft.id)); }}>{tr("deleteLocal")}</button></>}
    </div>
  </section>;
}
function PhotoList({photos}: {photos: Draft["photos"]}) {
  const { t } = useTranslation("modules");
  return <div className="mobilePhotos">{photos.map(photo => <PhotoPreview key={photo.id} photo={photo} label={t("mobile.photo")} />)}</div>;
}
function PhotoPreview({photo, label}: {photo: Draft["photos"][number]; label: string}) {
  const [url, setUrl] = useState(""); useEffect(() => { if (!photo.blob) return; const value = URL.createObjectURL(photo.blob); setUrl(value); return () => URL.revokeObjectURL(value); }, [photo.blob]);
  // Local object URLs are evidence previews; no remote or public attachment URL is exposed.
  // eslint-disable-next-line @next/next/no-img-element
  return url ? <a href={url} download={photo.name}><img src={url} alt={label} /></a> : <span>{label} ✓</span>;
}
