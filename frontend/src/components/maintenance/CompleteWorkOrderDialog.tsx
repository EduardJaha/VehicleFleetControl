"use client";

import { useEffect, useMemo, useState } from "react";
import { CreateEntityDialog } from "@/components/ui/CreateEntityDialog";
import { apiGet, apiPostForm, maintenanceApi } from "@/lib/api";
import { SERVICE_KM_INTERVALS, SERVICE_TYPES } from "@/lib/constants";
import { toApiDate, todayInputDate } from "@/lib/format";
import type { Attachment, Vehicle, WorkOrder, WorkOrderCompletionResult } from "@/lib/types";

type Props = {
  order: WorkOrder | null;
  open: boolean;
  onClose: () => void;
  onCompleted: (result: WorkOrderCompletionResult, uploadWarning?: string) => void | Promise<void>;
};

function initialState(order: WorkOrder | null) {
  return {
    actual_completion_date: todayInputDate(),
    completed_odometer_km: order?.completed_odometer_km ? String(order.completed_odometer_km) : "",
    workshop: order?.workshop ?? "",
    labor_cost: order?.labor_cost ? String(order.labor_cost) : "0",
    parts_cost: order?.parts_cost ? String(order.parts_cost) : "0",
    completion_notes: order?.completion_notes ?? "",
    create_service_record: true,
    service_type: "General Service",
    service_description: order?.description ?? order?.reported_issue ?? "",
    next_service_km_interval: "10000",
    next_service_date: "",
    resolve_source_reminder: Boolean(order?.source_reminder)
  };
}

export function CompleteWorkOrderDialog({ order, open, onClose, onCompleted }: Props) {
  const [form, setForm] = useState(() => initialState(order));
  const [bill, setBill] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open || !order) return;
    setForm(initialState(order));
    setBill(null);
    setError(null);
    apiGet<Vehicle>(`/vehicles/${order.vehicle_id}`).then((vehicle) => {
      setForm((current) => ({
        ...current,
        completed_odometer_km: current.completed_odometer_km || String(vehicle.odometer_km ?? "")
      }));
    }).catch(() => undefined);
  }, [open, order]);

  const total = useMemo(
    () => (Number(form.labor_cost || 0) + Number(form.parts_cost || 0)).toFixed(2),
    [form.labor_cost, form.parts_cost]
  );
  const mileageReminder = ["General Service", "Oil Change"].includes(form.service_type);
  const dateReminder = form.service_type === "Tire Change/Control";

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!order || submitting) return;
    setError(null);
    setSubmitting(true);
    try {
      const result = await maintenanceApi.completeWorkOrder(order.id, {
        actual_completion_date: toApiDate(form.actual_completion_date),
        completed_odometer_km: Number(form.completed_odometer_km),
        workshop: form.workshop || null,
        labor_cost: Number(form.labor_cost || 0),
        parts_cost: Number(form.parts_cost || 0),
        completion_notes: form.completion_notes || null,
        create_service_record: form.create_service_record,
        service_type: form.create_service_record ? form.service_type : null,
        service_description: form.create_service_record ? form.service_description || null : null,
        next_service_km_interval: form.create_service_record && mileageReminder ? Number(form.next_service_km_interval) : null,
        next_service_date: form.create_service_record && dateReminder && form.next_service_date ? toApiDate(form.next_service_date) : null,
        resolve_source_reminder: form.resolve_source_reminder
      });
      let uploadWarning: string | undefined;
      if (bill && result.service) {
        try {
          const data = new FormData();
          data.append("entity_type", "VehicleService");
          data.append("entity_id", String(result.service.id));
          data.append("category", "auto");
          data.append("file", bill);
          await apiPostForm<Attachment>("/files", data);
        } catch (uploadError) {
          uploadWarning = uploadError instanceof Error ? `Work Order completed, but the bill upload failed: ${uploadError.message}` : "Work Order completed, but the bill upload failed.";
        }
      }
      await onCompleted(result, uploadWarning);
      onClose();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Could not complete Work Order.");
    } finally {
      setSubmitting(false);
    }
  }

  return <CreateEntityDialog
    open={open}
    title={order ? `Complete Work Order #${order.id}` : "Complete Work Order"}
    description="Completion, linked Service, odometer, reminder, audit, and notification updates are committed together."
    busy={submitting}
    onClose={onClose}
  >
    <form className="form dialogForm" onSubmit={submit}>
      {error && <div className="error" role="alert">{error}</div>}
      <div className="formGrid">
        <div className="formRow"><label>Completion date</label><input className="input" type="date" max={todayInputDate()} required value={form.actual_completion_date} onChange={(e) => setForm({ ...form, actual_completion_date: e.target.value })} /></div>
        <div className="formRow"><label>Completed odometer</label><input className="input" type="number" min="0" required value={form.completed_odometer_km} onChange={(e) => setForm({ ...form, completed_odometer_km: e.target.value })} /></div>
        <div className="formRow"><label>Workshop</label><input className="input" value={form.workshop} onChange={(e) => setForm({ ...form, workshop: e.target.value })} /></div>
        <div className="formRow"><label>Calculated total</label><input className="input" readOnly value={total} /></div>
        <div className="formRow"><label>Labor cost</label><input className="input" type="number" min="0" step="0.01" required value={form.labor_cost} onChange={(e) => setForm({ ...form, labor_cost: e.target.value })} /></div>
        <div className="formRow"><label>Parts cost</label><input className="input" type="number" min="0" step="0.01" required value={form.parts_cost} onChange={(e) => setForm({ ...form, parts_cost: e.target.value })} /></div>
        <div className="formRow span2"><label>Completion notes</label><textarea className="input textarea" value={form.completion_notes} onChange={(e) => setForm({ ...form, completion_notes: e.target.value })} /></div>
        <label className="actions span2"><input type="checkbox" checked={form.create_service_record} onChange={(e) => setForm({ ...form, create_service_record: e.target.checked })} /> Create Service Record</label>
        {form.create_service_record && <>
          <div className="formRow"><label>Service type</label><select className="select" value={form.service_type} onChange={(e) => setForm({ ...form, service_type: e.target.value })}>{SERVICE_TYPES.map((value) => <option key={value}>{value}</option>)}</select></div>
          <div className="formRow"><label>Bill or invoice</label><input className="input" type="file" accept=".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/jpeg,image/png,image/webp" onChange={(e) => setBill(e.target.files?.[0] ?? null)} /><span className="muted">PDF up to 10 MB; JPEG, PNG, or WebP up to 8 MB.</span></div>
          <div className="formRow span2"><label>Service description</label><textarea className="input textarea" value={form.service_description} onChange={(e) => setForm({ ...form, service_description: e.target.value })} /></div>
          {mileageReminder && <div className="formRow"><label>Next service kilometre interval</label><select className="select" value={form.next_service_km_interval} onChange={(e) => setForm({ ...form, next_service_km_interval: e.target.value })}>{SERVICE_KM_INTERVALS.map((value) => <option key={value} value={value}>{value.toLocaleString()} km</option>)}</select></div>}
          {dateReminder && <div className="formRow"><label>Next service date</label><input className="input" type="date" min={form.actual_completion_date} required value={form.next_service_date} onChange={(e) => setForm({ ...form, next_service_date: e.target.value })} /></div>}
        </>}
        {order?.source_reminder && <label className="actions span2"><input type="checkbox" checked={form.resolve_source_reminder} onChange={(e) => setForm({ ...form, resolve_source_reminder: e.target.checked })} /> Resolve source reminder</label>}
      </div>
      <div className="actions dialogActions">
        <button className="secondaryButton" type="button" disabled={submitting} onClick={onClose}>Cancel</button>
        <button className="button" type="submit" disabled={submitting}>{submitting ? "Completing..." : "Complete Work Order"}</button>
      </div>
    </form>
  </CreateEntityDialog>;
}
