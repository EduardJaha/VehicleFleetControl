"use client";
import Link from "next/link";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { apiDownload, apiPostForm, apiPut } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ITEM_FLAGS } from "@/lib/inspection-templates";
import type { Attachment, Inspection, InspectionItem, InspectionItemStatus } from "@/lib/types";
import { translateStatus } from "@/i18n/translate";

export default function InspectionResults({ inspection, onSave }: { inspection: Inspection; onSave: (value: Inspection) => void }) {
  const { t } = useTranslation(["modules", "common"]);
  const { can, user } = useAuth();
  const [items, setItems] = useState(inspection.items);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const ownsDraft = can("inspections.create") && (inspection.created_by_user_id === user?.id || (!!user?.driver_id && inspection.driver_id === user.driver_id));
  const editable = (can("inspections.manage") || ownsDraft) && !inspection.completed_at && !inspection.archived;
  const tr = (key: string) => t(`modules:inspectionTemplates.${key}`);
  function patch(id: number | undefined, value: Partial<InspectionItem>) { setItems(current => current.map(item => item.id === id ? {...item, ...value} : item)); }
  async function save(complete: boolean) {
    setBusy(true); setError("");
    try {
      const value = await apiPut<Inspection>(`/inspections/${inspection.id}`, {
        vehicle_id: inspection.vehicle_id, driver_id: inspection.driver_id, inspection_type: inspection.inspection_type,
        inspection_date: inspection.inspection_date, template_id: inspection.template_id, notes: inspection.notes,
        complete, items: items.map(item => ({id: item.id, item_name: item.item_name, status: item.status, comment: item.comment, photo_attachment_ids: item.photo_attachment_ids || []}))
      });
      setItems(value.items); onSave(value);
    } catch (e) { setError(e instanceof Error ? e.message : tr("error")); } finally { setBusy(false); }
  }
  async function upload(item: InspectionItem, file: File) {
    setBusy(true); setError("");
    try {
      const form = new FormData(); form.append("entity_type", "Inspection"); form.append("entity_id", String(inspection.id)); form.append("category", "image"); form.append("file", file);
      const photo = await apiPostForm<Attachment>("/files", form);
      patch(item.id, {photo_attachment_ids: [...(item.photo_attachment_ids || []), photo.id]});
    } catch (e) { setError(e instanceof Error ? e.message : tr("error")); } finally { setBusy(false); }
  }
  return <section className="card detailCard"><h2>{inspection.template_snapshot?.name}</h2><p>{inspection.template_snapshot?.description}</p><p>{inspection.completed_at ? tr("completedLocked") : tr("snapshotHelp")}</p>
    {error && <div className="error" role="alert">{error}</div>}
    {items.map(item => <fieldset key={item.id} className="card spaced" disabled={busy}>
      <legend><strong>{item.item_name}</strong></legend><p>{item.item_snapshot?.description}</p>
      <p className="muted">{item.item_snapshot && tr(`categories.${item.item_snapshot.category}`)} · {ITEM_FLAGS.filter(flag => flag !== "is_active" && item.item_snapshot?.[flag]).map(flag => tr(`flags.${flag}`)).join(" · ")}</p>
      {editable ? <div className="formGrid">
        <label className="formRow">{t("common:labels.status")}<select className="select" value={item.status} onChange={e => patch(item.id, {status: e.target.value as InspectionItemStatus})}>{["Not Checked", "Pass", "Fail"].map(status => <option key={status} value={status}>{translateStatus(status)}</option>)}</select></label>
        <label className="formRow">{t("common:labels.comment")}<textarea className="input" value={item.comment || ""} onChange={e => patch(item.id, {comment: e.target.value})} /></label>
        <label className="formRow">{tr("photo")}<input type="file" accept="image/jpeg,image/png,image/webp,image/gif" onChange={e => {const file = e.target.files?.[0]; if (file) void upload(item, file); e.target.value = "";}} /></label>
      </div> : <p>{translateStatus(item.status)} · {item.comment}</p>}
      {item.work_order_id && <Link className="link" href={`/work-orders/${item.work_order_id}`}>{t("modules:inspections.workOrderCreated", {id: item.work_order_id})}</Link>}
      <div className="actions">{(item.photo_attachment_ids || []).map((id, index) => <button key={id} type="button" className="secondaryButton" onClick={() => void apiDownload(`/files/${id}/download`, `inspection-${inspection.id}-${id}`).catch(e => setError(e.message))}>{tr("photo")} {index + 1}</button>)}</div>
    </fieldset>)}
    {editable && <div className="actions"><button className="secondaryButton" disabled={busy} onClick={() => void save(false)}>{tr("saveResults")}</button><button className="button" disabled={busy} onClick={() => void save(true)}>{tr("complete")}</button></div>}
  </section>;
}
