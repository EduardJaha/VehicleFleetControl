"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiDelete, apiGet, apiPost, apiPut, buildQuery } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { DEFAULT_INSPECTION_ITEMS, INSPECTION_ITEM_STATUSES, INSPECTION_OVERALL_STATUSES, INSPECTION_TYPES } from "@/lib/constants";
import { toApiDate, toInputDate, todayInputDate } from "@/lib/format";
import type { ApiMessage, Inspection, InspectionItem, InspectionItemStatus, InspectionOverallStatus, InspectionPayload, InspectionType } from "@/lib/types";

type InspectionForm = {
  license_plate: string;
  driver_id: string;
  inspection_type: InspectionType;
  inspection_date: string;
  overall_status: "" | InspectionOverallStatus;
  notes: string;
  items: InspectionItem[];
};

const defaultItems = (): InspectionItem[] => DEFAULT_INSPECTION_ITEMS.map((item) => ({ item_name: item, status: "Not Checked", comment: "" }));

const initialForm: InspectionForm = {
  license_plate: "",
  driver_id: "",
  inspection_type: "Daily",
  inspection_date: todayInputDate(),
  overall_status: "",
  notes: "",
  items: defaultItems()
};

function inspectionToForm(inspection: Inspection): InspectionForm {
  return {
    license_plate: inspection.license_plate,
    driver_id: inspection.driver_id ? String(inspection.driver_id) : "",
    inspection_type: inspection.inspection_type,
    inspection_date: toInputDate(inspection.inspection_date),
    overall_status: inspection.overall_status,
    notes: inspection.notes ?? "",
    items: inspection.items.map((item) => ({ ...item, comment: item.comment ?? "" }))
  };
}

function formToPayload(form: InspectionForm): InspectionPayload {
  return {
    license_plate: form.license_plate,
    driver_id: form.driver_id ? Number(form.driver_id) : null,
    inspection_type: form.inspection_type,
    inspection_date: toApiDate(form.inspection_date),
    overall_status: form.overall_status || null,
    notes: form.notes || null,
    items: form.items.map((item) => ({
      item_name: item.item_name,
      status: item.status,
      comment: item.comment || null
    }))
  };
}

function statusClass(status: InspectionOverallStatus) {
  if (status === "Failed") return "dangerBadge";
  if (status === "Needs Review") return "warningBadge";
  return "badge";
}

export default function InspectionsPage() {
  const { can } = useAuth();
  const canWrite = can("inspectionsWrite");
  const [inspections, setInspections] = useState<Inspection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [form, setForm] = useState<InspectionForm>(initialForm);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [filters, setFilters] = useState({ license_plate: "", driver_id: "", inspection_type: "", overall_status: "", from_date: "", to_date: "" });

  async function loadInspections(currentFilters = filters) {
    setLoading(true);
    setError(null);
    try {
      const query = buildQuery({
        license_plate: currentFilters.license_plate,
        driver_id: currentFilters.driver_id,
        inspection_type: currentFilters.inspection_type,
        overall_status: currentFilters.overall_status,
        from_date: toApiDate(currentFilters.from_date),
        to_date: toApiDate(currentFilters.to_date)
      });
      setInspections(await apiGet<Inspection[]>(`/inspections${query}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load inspections");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadInspections();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const failedItemCount = useMemo(() => form.items.filter((item) => item.status === "Fail").length, [form.items]);

  function updateItem(index: number, patch: Partial<InspectionItem>) {
    setForm((current) => ({
      ...current,
      items: current.items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item)
    }));
  }

  function addItem() {
    setForm((current) => ({ ...current, items: [...current.items, { item_name: "", status: "Not Checked", comment: "" }] }));
  }

  function removeItem(index: number) {
    setForm((current) => ({ ...current, items: current.items.filter((_, itemIndex) => itemIndex !== index) }));
  }

  async function saveInspection(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    try {
      if (editingId) {
        const updated = await apiPut<Inspection>(`/inspections/${editingId}`, formToPayload(form));
        setMessage(`Inspection ${updated.id} updated.`);
      } else {
        const created = await apiPost<Inspection>("/inspections", formToPayload(form));
        setMessage(`Inspection ${created.id} created.`);
      }
      setForm(initialForm);
      setEditingId(null);
      await loadInspections();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save inspection");
    }
  }

  function startEdit(inspection: Inspection) {
    setEditingId(inspection.id);
    setForm(inspectionToForm(inspection));
    setError(null);
    setMessage(null);
  }

  function cancelEdit() {
    setEditingId(null);
    setForm(initialForm);
  }

  async function deleteInspection(inspection: Inspection) {
    if (!confirm(`Delete inspection ${inspection.id} for ${inspection.license_plate}?`)) return;
    setError(null);
    setMessage(null);
    try {
      const result = await apiDelete<ApiMessage>(`/inspections/${inspection.id}`);
      setMessage(result.message ?? "Inspection deleted.");
      await loadInspections();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete inspection");
    }
  }

  return (
    <section>
      <div className="header">
        <div>
          <h1>Inspections</h1>
          <p className="muted">Create vehicle inspection checklists, review failed items, and filter inspection history.</p>
        </div>
      </div>

      {error && <div className="error spaced">{error}</div>}
      {message && <div className="success spaced">{message}</div>}

      {canWrite && (
        <form onSubmit={saveInspection} className="form card fullWidthForm spaced">
          <h2>{editingId ? "Edit inspection" : "Create inspection"}</h2>
          {failedItemCount > 0 && <div className="error">This checklist has {failedItemCount} failed item(s). Overall status will not be saved as Passed.</div>}
          <div className="formGrid">
            <div className="formRow"><label>License plate</label><input className="input" value={form.license_plate} onChange={(event) => setForm({ ...form, license_plate: event.target.value })} placeholder="01-123-AB" required /></div>
            <div className="formRow"><label>Driver ID optional</label><input className="input" type="number" value={form.driver_id} onChange={(event) => setForm({ ...form, driver_id: event.target.value })} /></div>
            <div className="formRow"><label>Inspection type</label><select className="select" value={form.inspection_type} onChange={(event) => setForm({ ...form, inspection_type: event.target.value as InspectionType })}>{INSPECTION_TYPES.map((type) => <option key={type}>{type}</option>)}</select></div>
            <div className="formRow"><label>Inspection date</label><input className="input" type="date" value={form.inspection_date} onChange={(event) => setForm({ ...form, inspection_date: event.target.value })} required /></div>
            <div className="formRow"><label>Overall status</label><select className="select" value={form.overall_status} onChange={(event) => setForm({ ...form, overall_status: event.target.value as "" | InspectionOverallStatus })}><option value="">Auto</option>{INSPECTION_OVERALL_STATUSES.map((status) => <option key={status}>{status}</option>)}</select></div>
            <div className="formRow span2"><label>Notes</label><textarea className="input textarea" value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} /></div>
          </div>

          <div className="spaced">
            <div className="header">
              <h2>Checklist</h2>
              <button className="secondaryButton smallButton" type="button" onClick={addItem}>Add item</button>
            </div>
            <table className="table">
              <thead><tr><th>Item</th><th>Status</th><th>Comment</th><th>Actions</th></tr></thead>
              <tbody>
                {form.items.map((item, index) => (
                  <tr key={`${item.item_name}-${index}`}>
                    <td><input className="input" value={item.item_name} onChange={(event) => updateItem(index, { item_name: event.target.value })} required /></td>
                    <td><select className="select" value={item.status} onChange={(event) => updateItem(index, { status: event.target.value as InspectionItemStatus })}>{INSPECTION_ITEM_STATUSES.map((status) => <option key={status}>{status}</option>)}</select></td>
                    <td><input className="input" value={item.comment ?? ""} onChange={(event) => updateItem(index, { comment: event.target.value })} /></td>
                    <td><button className="dangerButton smallButton" type="button" onClick={() => removeItem(index)} disabled={form.items.length <= 1}>Remove</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="actions">
            <button className="button" type="submit">{editingId ? "Update inspection" : "Create inspection"}</button>
            {editingId && <button className="secondaryButton" type="button" onClick={cancelEdit}>Cancel</button>}
          </div>
        </form>
      )}

      <div className="card filtersGrid spaced">
        <input className="input" value={filters.license_plate} onChange={(event) => setFilters({ ...filters, license_plate: event.target.value })} placeholder="Plate" />
        <input className="input" type="number" value={filters.driver_id} onChange={(event) => setFilters({ ...filters, driver_id: event.target.value })} placeholder="Driver ID" />
        <select className="select" value={filters.inspection_type} onChange={(event) => setFilters({ ...filters, inspection_type: event.target.value })}><option value="">All types</option>{INSPECTION_TYPES.map((type) => <option key={type}>{type}</option>)}</select>
        <select className="select" value={filters.overall_status} onChange={(event) => setFilters({ ...filters, overall_status: event.target.value })}><option value="">All statuses</option>{INSPECTION_OVERALL_STATUSES.map((status) => <option key={status}>{status}</option>)}</select>
        <input className="input" type="date" value={filters.from_date} onChange={(event) => setFilters({ ...filters, from_date: event.target.value })} />
        <input className="input" type="date" value={filters.to_date} onChange={(event) => setFilters({ ...filters, to_date: event.target.value })} />
        <button className="button" type="button" onClick={() => void loadInspections()}>Apply filters</button>
      </div>

      {loading ? <div className="card">Loading inspections...</div> : (
        <table className="table">
          <thead><tr><th>Plate</th><th>Driver</th><th>Type</th><th>Date</th><th>Status</th><th>Failed</th><th>Notes</th>{canWrite && <th>Actions</th>}</tr></thead>
          <tbody>
            {inspections.map((inspection) => {
              const failed = inspection.items.filter((item) => item.status === "Fail").length;
              const workOrderHref = `/work-orders?inspection_id=${inspection.id}&license_plate=${encodeURIComponent(inspection.license_plate)}&title=${encodeURIComponent(`Inspection ${inspection.id} issue`)}&reported_issue=${encodeURIComponent(`${failed} failed checklist item(s)`)}`;
              return (
                <tr key={inspection.id}>
                  <td><strong>{inspection.license_plate}</strong></td>
                  <td>{inspection.driver_name ?? inspection.driver_id ?? "-"}</td>
                  <td>{inspection.inspection_type}</td>
                  <td>{inspection.inspection_date}</td>
                  <td><span className={statusClass(inspection.overall_status)}>{inspection.overall_status}</span></td>
                  <td>{failed > 0 ? <span className="dangerBadge">{failed}</span> : "0"}</td>
                  <td>{inspection.notes ?? "-"}</td>
                  {canWrite && <td><div className="actions">{failed > 0 && <Link className="secondaryButton smallButton" href={workOrderHref}>Work order</Link>}<button className="secondaryButton smallButton" type="button" onClick={() => startEdit(inspection)}>Edit</button><button className="dangerButton smallButton" type="button" onClick={() => void deleteInspection(inspection)}>Delete</button></div></td>}
                </tr>
              );
            })}
            {inspections.length === 0 && <tr><td colSpan={canWrite ? 8 : 7} className="muted">No inspections match your filters.</td></tr>}
          </tbody>
        </table>
      )}
    </section>
  );
}
