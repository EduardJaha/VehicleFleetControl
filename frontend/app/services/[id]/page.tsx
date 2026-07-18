"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiDownloadFile, maintenanceApi } from "@/lib/api";
import type { VehicleServiceDetail } from "@/lib/types";
import { formatMoney, LinkedRecordCard, MaintenancePageHeader, MaintenanceStatusBadge } from "@/components/maintenance/Maintenance";

function Details({ values }: { values: Array<[string, React.ReactNode]> }) { return <dl className="detailList">{values.map(([label, value]) => <div style={{ display: "contents" }} key={label}><dt>{label}</dt><dd>{value ?? "-"}</dd></div>)}</dl>; }

export default function ServiceDetailsPage({ params }: { params: { id: string } }) {
  const [service, setService] = useState<VehicleServiceDetail | null>(null); const [error, setError] = useState<string | null>(null);
  useEffect(() => { maintenanceApi.getService(params.id).then(setService).catch((err) => setError(err instanceof Error ? err.message : "Could not load Service")); }, [params.id]);
  if (error) return <div className="error">{error}</div>; if (!service) return <div className="card">Loading Service...</div>;
  return <section>
    <MaintenancePageHeader title={`Service #${service.id}`} description="Completed maintenance details, costs, reminders, attachments, and source information." actions={<Link className="secondaryButton" href="/services/overview">Back to Service History</Link>} />
    <div className="actions spaced"><MaintenanceStatusBadge status={service.status} /><span className="badge">Source: {service.source}</span></div>
    <div className="detailGrid spaced">
      <section className="card detailCard"><h2>Service information</h2><Details values={[["Service type", service.service_type], ["Service date", service.service_date], ["Vehicle", <Link key="vehicle" className="link" href={`/vehicles/${service.vehicle_id}`}>{service.license_plate}</Link>], ["Odometer", service.odometer_km ? `${service.odometer_km.toLocaleString()} km` : "-"], ["Workshop", service.workshop ?? "-"], ["Description", service.description ?? "-"]]} /></section>
      <section className="card detailCard"><h2>Cost information</h2><Details values={[["Labor cost", formatMoney(service.labor_cost)], ["Parts cost", formatMoney(service.parts_cost)], ["Total cost", formatMoney(service.total_cost)]]} /></section>
      <section className="card detailCard"><h2>Reminder information</h2><Details values={[["Next service date", service.next_service_date ?? "-"], ["Next service odometer", service.next_service_odometer_km ? `${service.next_service_odometer_km.toLocaleString()} km` : "-"], ["Next service interval", service.next_service_km_interval ? `${service.next_service_km_interval.toLocaleString()} km` : "-"], ["Reminder status", service.reminder_status ? <MaintenanceStatusBadge key="reminder-status" status={service.reminder_status} /> : "No reminder"]]} /></section>
      <section className="card detailCard"><h2>Attachments</h2>{service.bills.length ? <div className="recordList">{service.bills.map((file) => <div className="recordRow" key={file.id}><div><strong>{file.attachment_type}</strong><div className="muted">Uploaded {new Date(file.uploaded_at).toLocaleString()}</div></div><button className="secondaryButton smallButton" type="button" onClick={() => void apiDownloadFile(file.file_path, `service-${service.id}-attachment`)}>Download file</button></div>)}</div> : <div className="maintenanceEmpty muted">No bills, invoices, or other files are attached.</div>}</section>
    </div>
    <section className="card detailCard"><h2>Source information</h2>{service.linked_work_order ? <LinkedRecordCard title={`Created from Work Order #${service.linked_work_order.id}`} description={`${service.linked_work_order.title} · ${service.linked_work_order.status}`} href={`/work-orders/${service.linked_work_order.id}`} /> : <LinkedRecordCard title="Source: Manually registered Service" description="This is a complete and valid historical Service record." empty="" />}</section>
  </section>;
}
