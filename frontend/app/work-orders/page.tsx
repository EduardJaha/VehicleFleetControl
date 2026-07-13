"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { apiDelete, apiGet, apiPost, apiPut, buildQuery } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { WORK_ORDER_PRIORITIES, WORK_ORDER_STATUSES } from "@/lib/constants";
import { toApiDate, toInputDate, todayInputDate } from "@/lib/format";
import type { ApiMessage, WorkOrder, WorkOrderPayload, WorkOrderPriority, WorkOrderStatus } from "@/lib/types";

type WorkOrderForm = {
  license_plate: string;
  driver_id: string;
  inspection_id: string;
  title: string;
  description: string;
  reported_issue: string;
  priority: WorkOrderPriority;
  status: WorkOrderStatus;
  requested_by: string;
  assigned_to: string;
  workshop: string;
  expected_completion_date: string;
  actual_completion_date: string;
  labor_cost: string;
  parts_cost: string;
  notes: string;
};

function initialFormFromParams(searchParams?: URLSearchParams): WorkOrderForm {
  return {
    license_plate: searchParams?.get("license_plate") ?? "",
    driver_id: "",
    inspection_id: searchParams?.get("inspection_id") ?? "",
    title: searchParams?.get("title") ?? "",
    description: "",
    reported_issue: searchParams?.get("reported_issue") ?? "",
    priority: "Medium",
    status: "Open",
    requested_by: "",
    assigned_to: "",
    workshop: "",
    expected_completion_date: "",
    actual_completion_date: "",
    labor_cost: "",
    parts_cost: "",
    notes: ""
  };
}

function workOrderToForm(workOrder: WorkOrder): WorkOrderForm {
  return {
    license_plate: workOrder.license_plate,
    driver_id: workOrder.driver_id ? String(workOrder.driver_id) : "",
    inspection_id: workOrder.inspection_id ? String(workOrder.inspection_id) : "",
    title: workOrder.title,
    description: workOrder.description ?? "",
    reported_issue: workOrder.reported_issue ?? "",
    priority: workOrder.priority,
    status: workOrder.status,
    requested_by: workOrder.requested_by ?? "",
    assigned_to: workOrder.assigned_to ?? "",
    workshop: workOrder.workshop ?? "",
    expected_completion_date: toInputDate(workOrder.expected_completion_date ?? ""),
    actual_completion_date: toInputDate(workOrder.actual_completion_date ?? ""),
    labor_cost: workOrder.labor_cost ? String(workOrder.labor_cost) : "",
    parts_cost: workOrder.parts_cost ? String(workOrder.parts_cost) : "",
    notes: workOrder.notes ?? ""
  };
}

function formToPayload(form: WorkOrderForm): WorkOrderPayload {
  return {
    license_plate: form.license_plate || null,
    driver_id: form.driver_id ? Number(form.driver_id) : null,
    inspection_id: form.inspection_id ? Number(form.inspection_id) : null,
    title: form.title,
    description: form.description || null,
    reported_issue: form.reported_issue || null,
    priority: form.priority,
    status: form.status,
    requested_by: form.requested_by || null,
    assigned_to: form.assigned_to || null,
    workshop: form.workshop || null,
    expected_completion_date: form.expected_completion_date ? toApiDate(form.expected_completion_date) : null,
    actual_completion_date: form.actual_completion_date ? toApiDate(form.actual_completion_date) : null,
    labor_cost: form.labor_cost ? Number(form.labor_cost) : null,
    parts_cost: form.parts_cost ? Number(form.parts_cost) : null,
    notes: form.notes || null
  };
}

function statusClass(status: WorkOrderStatus) {
  if (status === "Completed") return "badge";
  if (status === "Cancelled") return "secondaryButton smallButton";
  if (status === "Waiting for Parts") return "warningBadge";
  return "badge";
}

function isOverdue(workOrder: WorkOrder) {
  if (!workOrder.expected_completion_date || ["Completed", "Cancelled"].includes(workOrder.status)) return false;
  const expected = new Date(toInputDate(workOrder.expected_completion_date));
  const today = new Date(todayInputDate());
  return expected < today;
}

export default function WorkOrdersPage() {
  const searchParams = useSearchParams();
  const { can } = useAuth();
  const canWrite = can("workOrdersWrite");
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [form, setForm] = useState<WorkOrderForm>(() => initialFormFromParams(searchParams));
  const [editingId, setEditingId] = useState<number | null>(null);
  const [filters, setFilters] = useState({ search: "", license_plate: "", status: "", priority: "", workshop: "", from_date: "", to_date: "" });

  async function loadWorkOrders(currentFilters = filters) {
    setLoading(true);
    setError(null);
    try {
      const query = buildQuery({
        search: currentFilters.search,
        license_plate: currentFilters.license_plate,
        status: currentFilters.status,
        priority: currentFilters.priority,
        workshop: currentFilters.workshop,
        from_date: toApiDate(currentFilters.from_date),
        to_date: toApiDate(currentFilters.to_date)
      });
      setWorkOrders(await apiGet<WorkOrder[]>(`/work-orders${query}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load work orders");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadWorkOrders();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const totals = useMemo(() => workOrders.reduce((sum, order) => sum + Number(order.total_cost ?? 0), 0), [workOrders]);

  async function saveWorkOrder(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    try {
      if (editingId) {
        const updated = await apiPut<WorkOrder>(`/work-orders/${editingId}`, formToPayload(form));
        setMessage(`Work order ${updated.id} updated.`);
      } else {
        const created = await apiPost<WorkOrder>("/work-orders", formToPayload(form));
        setMessage(`Work order ${created.id} created.`);
      }
      setForm(initialFormFromParams());
      setEditingId(null);
      await loadWorkOrders();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save work order");
    }
  }

  function startEdit(workOrder: WorkOrder) {
    setEditingId(workOrder.id);
    setForm(workOrderToForm(workOrder));
    setMessage(null);
    setError(null);
  }

  function cancelEdit() {
    setEditingId(null);
    setForm(initialFormFromParams());
  }

  async function updateStatus(workOrder: WorkOrder, status: WorkOrderStatus) {
    setError(null);
    setMessage(null);
    try {
      const payload = {
        status,
        actual_completion_date: status === "Completed" && !workOrder.actual_completion_date ? toApiDate(todayInputDate()) : workOrder.actual_completion_date
      };
      const updated = await apiPut<WorkOrder>(`/work-orders/${workOrder.id}/status`, payload);
      setMessage(`Work order ${updated.id} status updated.`);
      await loadWorkOrders();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update status");
    }
  }

  async function deleteWorkOrder(workOrder: WorkOrder) {
    if (!confirm(`Delete work order ${workOrder.id}: ${workOrder.title}?`)) return;
    setError(null);
    setMessage(null);
    try {
      const result = await apiDelete<ApiMessage>(`/work-orders/${workOrder.id}`);
      setMessage(result.message ?? "Work order deleted.");
      await loadWorkOrders();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete work order");
    }
  }

  return (
    <section>
      <div className="header">
        <div>
          <h1>Work Orders</h1>
          <p className="muted">Track maintenance requests, priorities, status, workshops, and costs.</p>
        </div>
      </div>

      {error && <div className="error spaced">{error}</div>}
      {message && <div className="success spaced">{message}</div>}

      {canWrite && (
        <form onSubmit={saveWorkOrder} className="form card fullWidthForm spaced">
          <h2>{editingId ? "Edit work order" : "Create work order"}</h2>
          <div className="formGrid">
            <div className="formRow"><label>License plate</label><input className="input" value={form.license_plate} onChange={(event) => setForm({ ...form, license_plate: event.target.value })} placeholder="01-123-AB" required /></div>
            <div className="formRow"><label>Title</label><input className="input" value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} required /></div>
            <div className="formRow"><label>Driver ID optional</label><input className="input" type="number" value={form.driver_id} onChange={(event) => setForm({ ...form, driver_id: event.target.value })} /></div>
            <div className="formRow"><label>Inspection ID optional</label><input className="input" type="number" value={form.inspection_id} onChange={(event) => setForm({ ...form, inspection_id: event.target.value })} /></div>
            <div className="formRow"><label>Priority</label><select className="select" value={form.priority} onChange={(event) => setForm({ ...form, priority: event.target.value as WorkOrderPriority })}>{WORK_ORDER_PRIORITIES.map((priority) => <option key={priority}>{priority}</option>)}</select></div>
            <div className="formRow"><label>Status</label><select className="select" value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value as WorkOrderStatus })}>{WORK_ORDER_STATUSES.map((status) => <option key={status}>{status}</option>)}</select></div>
            <div className="formRow"><label>Requested by</label><input className="input" value={form.requested_by} onChange={(event) => setForm({ ...form, requested_by: event.target.value })} /></div>
            <div className="formRow"><label>Assigned to</label><input className="input" value={form.assigned_to} onChange={(event) => setForm({ ...form, assigned_to: event.target.value })} /></div>
            <div className="formRow"><label>Workshop</label><input className="input" value={form.workshop} onChange={(event) => setForm({ ...form, workshop: event.target.value })} /></div>
            <div className="formRow"><label>Expected completion</label><input className="input" type="date" value={form.expected_completion_date} onChange={(event) => setForm({ ...form, expected_completion_date: event.target.value })} /></div>
            <div className="formRow"><label>Actual completion</label><input className="input" type="date" value={form.actual_completion_date} onChange={(event) => setForm({ ...form, actual_completion_date: event.target.value })} required={form.status === "Completed"} /></div>
            <div className="formRow"><label>Labor cost</label><input className="input" type="number" step="0.01" value={form.labor_cost} onChange={(event) => setForm({ ...form, labor_cost: event.target.value })} /></div>
            <div className="formRow"><label>Parts cost</label><input className="input" type="number" step="0.01" value={form.parts_cost} onChange={(event) => setForm({ ...form, parts_cost: event.target.value })} /></div>
            <div className="formRow span2"><label>Reported issue</label><textarea className="input textarea" value={form.reported_issue} onChange={(event) => setForm({ ...form, reported_issue: event.target.value })} /></div>
            <div className="formRow span2"><label>Description</label><textarea className="input textarea" value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></div>
            <div className="formRow span2"><label>Notes</label><textarea className="input textarea" value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} /></div>
          </div>
          <div className="actions">
            <button className="button" type="submit">{editingId ? "Update work order" : "Create work order"}</button>
            {editingId && <button className="secondaryButton" type="button" onClick={cancelEdit}>Cancel</button>}
          </div>
        </form>
      )}

      <div className="card filtersGrid spaced">
        <input className="input" value={filters.search} onChange={(event) => setFilters({ ...filters, search: event.target.value })} placeholder="Search title, issue, assignee" />
        <input className="input" value={filters.license_plate} onChange={(event) => setFilters({ ...filters, license_plate: event.target.value })} placeholder="Plate" />
        <select className="select" value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })}><option value="">All statuses</option>{WORK_ORDER_STATUSES.map((status) => <option key={status}>{status}</option>)}</select>
        <select className="select" value={filters.priority} onChange={(event) => setFilters({ ...filters, priority: event.target.value })}><option value="">All priorities</option>{WORK_ORDER_PRIORITIES.map((priority) => <option key={priority}>{priority}</option>)}</select>
        <input className="input" value={filters.workshop} onChange={(event) => setFilters({ ...filters, workshop: event.target.value })} placeholder="Workshop" />
        <input className="input" type="date" value={filters.from_date} onChange={(event) => setFilters({ ...filters, from_date: event.target.value })} />
        <input className="input" type="date" value={filters.to_date} onChange={(event) => setFilters({ ...filters, to_date: event.target.value })} />
        <button className="button" type="button" onClick={() => void loadWorkOrders()}>Apply filters</button>
      </div>

      <p className="muted">Showing {workOrders.length} work order(s). Total visible cost: {totals.toFixed(2)}</p>
      {loading ? <div className="card">Loading work orders...</div> : (
        <table className="table">
          <thead><tr><th>Plate</th><th>Title</th><th>Priority</th><th>Status</th><th>Workshop</th><th>Expected</th><th>Assigned</th><th>Total</th>{canWrite && <th>Actions</th>}</tr></thead>
          <tbody>
            {workOrders.map((workOrder) => (
              <tr key={workOrder.id} className={workOrder.priority === "Critical" ? "criticalRow" : isOverdue(workOrder) ? "overdueRow" : undefined}>
                <td><strong>{workOrder.license_plate}</strong></td>
                <td>{workOrder.title}<br />{workOrder.inspection_id && <span className="muted">Inspection #{workOrder.inspection_id}</span>}</td>
                <td><span className={workOrder.priority === "Critical" ? "dangerBadge" : workOrder.priority === "High" ? "warningBadge" : "badge"}>{workOrder.priority}</span></td>
                <td>{canWrite ? <select className="select compactInput" value={workOrder.status} onChange={(event) => void updateStatus(workOrder, event.target.value as WorkOrderStatus)}>{WORK_ORDER_STATUSES.map((status) => <option key={status}>{status}</option>)}</select> : <span className={statusClass(workOrder.status)}>{workOrder.status}</span>}</td>
                <td>{workOrder.workshop ?? "-"}</td>
                <td>{workOrder.expected_completion_date ? <>{workOrder.expected_completion_date}{isOverdue(workOrder) && <br />}{isOverdue(workOrder) && <span className="dangerBadge">Overdue</span>}</> : "-"}</td>
                <td>{workOrder.assigned_to ?? workOrder.driver_name ?? "-"}</td>
                <td>{workOrder.total_cost ?? "-"}</td>
                {canWrite && <td><div className="actions"><button className="secondaryButton smallButton" type="button" onClick={() => startEdit(workOrder)}>Edit</button><button className="dangerButton smallButton" type="button" onClick={() => void deleteWorkOrder(workOrder)}>Delete</button></div></td>}
              </tr>
            ))}
            {workOrders.length === 0 && <tr><td colSpan={canWrite ? 9 : 8} className="muted">No work orders match your filters.</td></tr>}
          </tbody>
        </table>
      )}
    </section>
  );
}
