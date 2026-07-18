"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { maintenanceApi } from "@/lib/api";
import type { WorkOrder } from "@/lib/types";
import { formatMoney, LinkedRecordCard, MaintenancePageHeader, MaintenancePriorityBadge, MaintenanceStatusBadge } from "@/components/maintenance/Maintenance";
import { CompleteWorkOrderDialog } from "@/components/maintenance/CompleteWorkOrderDialog";
import { useAuth } from "@/lib/auth";

function Details({ values }: { values: Array<[string, React.ReactNode]> }) {
  return <dl className="detailList">{values.map(([label, value]) => <div key={label} style={{ display: "contents" }}><dt>{label}</dt><dd>{value ?? "-"}</dd></div>)}</dl>;
}

export default function WorkOrderDetailsPage({ params }: { params: { id: string } }) {
  const [order, setOrder] = useState<WorkOrder | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [completionOpen, setCompletionOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const { can } = useAuth();
  const load = () => maintenanceApi.getWorkOrder(params.id).then(setOrder).catch((err) => setError(err instanceof Error ? err.message : "Could not load Work Order"));
  useEffect(() => { void load(); }, [params.id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (error) return <div className="error">{error}</div>;
  if (!order) return <div className="card">Loading Work Order...</div>;
  return (
    <section>
      <MaintenancePageHeader title={`Work Order #${order.id}`} description="Work Order information, assignment, completion, costs, and connected maintenance records." actions={<Link className="secondaryButton" href="/work-orders">Back to Work Orders</Link>} />
      {message && <div className="success spaced">{message}</div>}
      <div className="actions spaced"><MaintenanceStatusBadge status={order.status} /><MaintenancePriorityBadge priority={order.priority} /><span className="badge">Source: {order.source}</span></div>
      {can("workOrdersWrite") && !["Completed", "Cancelled"].includes(order.status) && <div className="actions spaced"><button className="button" type="button" onClick={() => setCompletionOpen(true)}>Complete Work Order</button></div>}
      <div className="detailGrid spaced">
        <section className="card detailCard"><h2>Work Order information</h2><Details values={[
          ["ID", `#${order.id}`], ["Title", order.title], ["Description", order.description ?? "-"], ["Reported issue", order.reported_issue ?? "-"],
          ["Vehicle", <Link key="vehicle" className="link" href={`/vehicles/${order.vehicle_id}`}>{order.license_plate}</Link>], ["Priority", <MaintenancePriorityBadge key="priority" priority={order.priority} />],
          ["Status", <MaintenanceStatusBadge key="status" status={order.status} />], ["Source", order.source], ["Created", new Date(order.created_at).toLocaleString()],
          ["Expected completion", order.expected_completion_date ?? "-"], ["Actual completion", order.actual_completion_date ?? "-"]
        ]} /></section>
        <section className="card detailCard"><h2>Assignment information</h2><Details values={[
          ["Assigned person", order.assigned_to ?? order.driver_name ?? "-"], ["Workshop", order.workshop ?? "-"], ["Requested by", order.requested_by ?? "-"], ["Created by", order.created_by ?? "Legacy record"]
        ]} /></section>
        <section className="card detailCard"><h2>Cost information</h2><Details values={[["Labor cost", formatMoney(order.labor_cost)], ["Parts cost", formatMoney(order.parts_cost)], ["Total cost", formatMoney(order.total_cost)]]} /></section>
        <section className="card detailCard"><h2>Completion information</h2><Details values={[
          ["Completed odometer", order.completed_odometer_km ? `${order.completed_odometer_km.toLocaleString()} km` : "-"], ["Completion date", order.actual_completion_date ?? "-"],
          ["Completion notes", order.completion_notes ?? "-"], ["Completed by", order.completed_by ?? "-"]
        ]} /></section>
      </div>
      <section className="card detailCard">
        <h2>Related maintenance records</h2>
        <div className="linkedRecords">
          <LinkedRecordCard title="Source Inspection" description={order.source_inspection ? `${order.source_inspection.inspection_type} · ${order.source_inspection.overall_status}` : undefined} href={order.source_inspection ? `/inspections/${order.source_inspection.id}` : undefined} empty="No source Inspection is linked." />
          <LinkedRecordCard title="Source Service Reminder" description={order.source_reminder ? `${order.source_reminder.service_type} · ${order.source_reminder.status}` : undefined} href={order.source_reminder ? `/services/reminders?reminder_id=${order.source_reminder.id}` : undefined} empty="No source Service Reminder is linked." />
          <LinkedRecordCard title="Linked Service" description={order.linked_service ? `${order.linked_service.service_type} · ${order.linked_service.service_date}` : undefined} href={order.linked_service ? `/services/${order.linked_service.id}` : undefined} empty="No Service record is linked to this Work Order." />
        </div>
        {!order.linked_service && order.status === "Completed" && <div className="actions" style={{ marginTop: 14 }}><Link className="button" href={`/services/overview?work_order_id=${order.id}&license_plate=${encodeURIComponent(order.license_plate)}`}>Create linked Service</Link></div>}
      </section>
      <CompleteWorkOrderDialog
        order={order}
        open={completionOpen}
        onClose={() => setCompletionOpen(false)}
        onCompleted={async (completed, uploadWarning) => {
          setMessage(uploadWarning ?? `Work Order #${completed.work_order.id} completed${completed.service ? ` and linked to Service #${completed.service.id}` : ""}.`);
          await load();
        }}
      />
    </section>
  );
}
