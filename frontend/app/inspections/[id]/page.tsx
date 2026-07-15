"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { maintenanceApi } from "@/lib/api";
import type { Inspection } from "@/lib/types";
import { LinkedRecordCard, MaintenancePageHeader, MaintenanceStatusBadge, MaintenanceTable } from "@/components/maintenance/Maintenance";

export default function InspectionDetailsPage({ params }: { params: { id: string } }) {
  const [inspection, setInspection] = useState<Inspection | null>(null); const [error, setError] = useState<string | null>(null);
  useEffect(() => { maintenanceApi.getInspection(params.id).then(setInspection).catch((err) => setError(err instanceof Error ? err.message : "Could not load Inspection")); }, [params.id]);
  if (error) return <div className="error">{error}</div>; if (!inspection) return <div className="card">Loading Inspection...</div>;
  const failed = inspection.items.filter((item) => item.status === "Fail");
  return <section>
    <MaintenancePageHeader title={`Inspection #${inspection.id}`} description="Inspection checklist, failed items, inspector, and connected Work Order." actions={<Link className="secondaryButton" href="/inspections">Back to Inspections</Link>} />
    <div className="detailGrid spaced"><section className="card detailCard"><h2>Inspection information</h2><dl className="detailList"><dt>Vehicle</dt><dd><Link className="link" href={`/vehicles/${inspection.vehicle_id}`}>{inspection.license_plate}</Link></dd><dt>Driver</dt><dd>{inspection.driver_name ?? inspection.driver_id ?? "-"}</dd><dt>Inspection type</dt><dd>{inspection.inspection_type}</dd><dt>Inspection date</dt><dd>{inspection.inspection_date}</dd><dt>Overall status</dt><dd><MaintenanceStatusBadge status={inspection.overall_status} /></dd><dt>Inspector</dt><dd>{inspection.inspector ?? "-"}</dd><dt>Notes</dt><dd>{inspection.notes ?? "-"}</dd></dl></section><section className="card detailCard"><h2>Related maintenance</h2><LinkedRecordCard title={inspection.linked_work_order ? `Work Order #${inspection.linked_work_order.id} created` : "Created Work Order"} description={inspection.linked_work_order ? `${inspection.linked_work_order.title} · ${inspection.linked_work_order.status}` : undefined} href={inspection.linked_work_order ? `/work-orders/${inspection.linked_work_order.id}` : undefined} empty="No Work Order has been created from this Inspection." />{failed.length > 0 && !inspection.linked_work_order && <div className="actions" style={{ marginTop: 14 }}><Link className="button" href={`/work-orders?inspection_id=${inspection.id}&license_plate=${encodeURIComponent(inspection.license_plate)}&title=${encodeURIComponent(`Inspection ${inspection.id} issue`)}&reported_issue=${encodeURIComponent(`${failed.length} failed checklist item(s): ${failed.map((item) => item.item_name).join(", ")}`)}`}>Create Work Order</Link></div>}</section></div>
    <section className="card detailCard"><h2>Checklist</h2><MaintenanceTable><thead><tr><th>Item</th><th>Status</th><th>Comment</th></tr></thead><tbody>{inspection.items.map((item) => <tr key={item.id ?? item.item_name} className={item.status === "Fail" ? "criticalRow" : undefined}><td>{item.item_name}</td><td><MaintenanceStatusBadge status={item.status} /></td><td>{item.comment ?? "-"}</td></tr>)}</tbody></MaintenanceTable></section>
  </section>;
}
