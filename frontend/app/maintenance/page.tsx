"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { maintenanceApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { MaintenanceRecordSummary, MaintenanceSummary } from "@/lib/types";
import {
  formatMoney, MaintenanceEmptyState, MaintenanceKpiCard, MaintenancePageHeader,
  MaintenancePriorityBadge, MaintenanceStatusBadge
} from "@/components/maintenance/Maintenance";

function RecordSection({ title, items, empty }: { title: string; items: MaintenanceRecordSummary[]; empty: string }) {
  return (
    <section className="card maintenanceSection">
      <h2>{title}</h2>
      {!items.length ? <MaintenanceEmptyState>{empty}</MaintenanceEmptyState> : (
        <div className="recordList">
          {items.map((item) => (
            <div className="recordRow" key={`${item.record_type}-${item.id}`}>
              <div>
                <div className="recordTitle"><Link className="link" href={item.href}>{item.title}</Link><MaintenanceStatusBadge status={item.status} /><MaintenancePriorityBadge priority={item.priority} /></div>
                <div className="recordMeta"><strong>{item.license_plate}</strong><span>{item.vehicle}</span>{item.due_date && <span>Due {item.due_date}</span>}{item.assigned_to && <span>{item.assigned_to}</span>}{item.cost !== null && item.cost !== undefined && <span>{formatMoney(item.cost)}</span>}</div>
                {item.description && <div className="muted">{item.description}</div>}
              </div>
              <Link className="secondaryButton smallButton" href={item.href}>View</Link>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export default function MaintenanceDashboardPage() {
  const { user } = useAuth();
  const [summary, setSummary] = useState<MaintenanceSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    maintenanceApi.getSummary().then((data) => { if (active) setSummary(data); }).catch((err) => { if (active) setError(err instanceof Error ? err.message : "Could not load Maintenance Dashboard"); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  if (user?.role === "driver") return <div className="error">You do not have permission to view the Maintenance Dashboard.</div>;

  return (
    <section>
      <MaintenancePageHeader title="Maintenance Dashboard" description="Operational view of the complete inspection, repair, service, and reminder lifecycle." />
      {error && <div className="error spaced">{error}</div>}
      {loading && <div className="card">Loading maintenance summary...</div>}
      {summary && (
        <>
          <div className="kpiGrid spaced">
            <MaintenanceKpiCard label="Open Work Orders" value={summary.open_work_orders} href="/work-orders?status=Open" />
            <MaintenanceKpiCard label="Assigned Work Orders" value={summary.assigned_work_orders} href="/work-orders?status=Assigned" />
            <MaintenanceKpiCard label="Work Orders In Progress" value={summary.in_progress_work_orders} href="/work-orders?status=In+Progress" />
            <MaintenanceKpiCard label="Waiting for Parts" value={summary.waiting_for_parts_work_orders} href="/work-orders?status=Waiting+for+Parts" tone="warning" />
            <MaintenanceKpiCard label="Critical Work Orders" value={summary.critical_work_orders_count} href="/work-orders?priority=Critical" tone="danger" />
            <MaintenanceKpiCard label="Overdue Work Orders" value={summary.overdue_work_orders_count} href="/work-orders?overdue_only=true" tone="danger" />
            <MaintenanceKpiCard label="Completed Work Orders This Month" value={summary.completed_work_orders_this_month} href="/work-orders?status=Completed" />
            <MaintenanceKpiCard label="Services Completed This Month" value={summary.services_completed_this_month} href="/services/overview" />
            <MaintenanceKpiCard label="Upcoming Service Reminders" value={summary.upcoming_reminders_count} href="/services/reminders" />
            <MaintenanceKpiCard label="Overdue Service Reminders" value={summary.overdue_reminders_count} href="/services/reminders?overdue_only=true" tone="danger" />
            <MaintenanceKpiCard label="Failed Inspections" value={summary.failed_inspections_count} href="/inspections?overall_status=Failed" tone="danger" />
            <MaintenanceKpiCard label="Inspections Needing Review" value={summary.inspections_needing_review_count} href="/inspections?overall_status=Needs+Review" tone="warning" />
            <MaintenanceKpiCard label="Monthly Maintenance Cost" value={formatMoney(summary.monthly_maintenance_cost)} />
          </div>

          <div className="maintenanceSections spaced">
            <RecordSection title="Critical Work Orders" items={summary.critical_work_orders} empty="No critical Work Orders found." />
            <RecordSection title="Overdue Work Orders" items={summary.overdue_work_orders} empty="No overdue Work Orders found." />
            <RecordSection title="Overdue Service Reminders" items={summary.overdue_service_reminders} empty="No overdue Service Reminders." />
            <RecordSection title="Failed Inspections" items={summary.failed_inspections} empty="No failed Inspections." />
            <RecordSection title="Vehicles Currently In Service" items={summary.vehicles_in_service} empty="No vehicles are currently in service." />
          </div>

          <h2>Recent Maintenance Activity</h2>
          <div className="maintenanceSections">
            <RecordSection title="Recently Created Work Orders" items={summary.recently_created_work_orders} empty="No Work Orders have been created." />
            <RecordSection title="Recently Completed Work Orders" items={summary.recently_completed_work_orders} empty="No Work Orders have been completed." />
            <RecordSection title="Recent Services" items={summary.recent_services} empty="No Service records have been created." />
            <RecordSection title="Recent Inspections" items={summary.recent_inspections} empty="No Inspections have been recorded." />
          </div>
        </>
      )}
    </section>
  );
}
