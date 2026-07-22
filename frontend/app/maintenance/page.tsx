"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { maintenanceApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { MaintenanceRecordSummary, MaintenanceSummary } from "@/lib/types";
import {
  MaintenanceEmptyState, MaintenanceKpiCard, MaintenancePageHeader,
  MaintenancePriorityBadge, MaintenanceStatusBadge
} from "@/components/maintenance/Maintenance";
import { useLanguage } from "@/components/i18n/LanguageProvider";

function RecordSection({ title, items, empty }: { title: string; items: MaintenanceRecordSummary[]; empty: string }) {
  const { t } = useTranslation(["modules", "common"]);
  const { formatCurrency } = useLanguage();
  return (
    <section className="card maintenanceSection">
      <h2>{title}</h2>
      {!items.length ? <MaintenanceEmptyState>{empty}</MaintenanceEmptyState> : (
        <div className="recordList">
          {items.map((item) => (
            <div className="recordRow" key={`${item.record_type}-${item.id}`}>
              <div>
                <div className="recordTitle"><Link className="link" href={item.href}>{item.title}</Link><MaintenanceStatusBadge status={item.status} /><MaintenancePriorityBadge priority={item.priority} /></div>
                <div className="recordMeta"><strong>{item.license_plate}</strong><span>{item.vehicle}</span>{item.due_date && <span>{t("modules:maintenance.due", { date: item.due_date })}</span>}{item.assigned_to && <span>{item.assigned_to}</span>}{item.cost !== null && item.cost !== undefined && <span>{formatCurrency(item.cost)}</span>}</div>
                {item.description && <div className="muted">{item.description}</div>}
              </div>
              <Link className="secondaryButton smallButton" href={item.href}>{t("common:actions.view")}</Link>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export default function MaintenanceDashboardPage() {
  const { t } = useTranslation(["modules", "common"]);
  const { formatCurrency } = useLanguage();
  const { user } = useAuth();
  const [summary, setSummary] = useState<MaintenanceSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    maintenanceApi.getSummary().then((data) => { if (active) setSummary(data); }).catch((err) => { if (active) setError(err instanceof Error ? err.message : t("modules:maintenance.loadError")); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  if (user?.role === "driver") return <div className="error">{t("modules:maintenance.accessDenied")}</div>;

  return (
    <section>
      <MaintenancePageHeader title={t("modules:maintenance.title")} description={t("modules:maintenance.description")} />
      {error && <div className="error spaced">{error}</div>}
      {loading && <div className="card">{t("modules:maintenance.loading")}</div>}
      {summary && (
        <>
          <div className="kpiGrid spaced">
            <MaintenanceKpiCard label={t("modules:maintenance.openWorkOrders")} value={summary.open_work_orders} href="/work-orders?status=Open" />
            <MaintenanceKpiCard label={t("modules:maintenance.assignedWorkOrders")} value={summary.assigned_work_orders} href="/work-orders?status=Assigned" />
            <MaintenanceKpiCard label={t("modules:maintenance.workOrdersInProgress")} value={summary.in_progress_work_orders} href="/work-orders?status=In+Progress" />
            <MaintenanceKpiCard label={t("modules:maintenance.waitingForParts")} value={summary.waiting_for_parts_work_orders} href="/work-orders?status=Waiting+for+Parts" tone="warning" />
            <MaintenanceKpiCard label={t("modules:maintenance.criticalWorkOrders")} value={summary.critical_work_orders_count} href="/work-orders?priority=Critical" tone="danger" />
            <MaintenanceKpiCard label={t("modules:maintenance.overdueWorkOrders")} value={summary.overdue_work_orders_count} href="/work-orders?overdue_only=true" tone="danger" />
            <MaintenanceKpiCard label={t("modules:maintenance.completedWorkOrdersMonth")} value={summary.completed_work_orders_this_month} href="/work-orders?status=Completed" />
            <MaintenanceKpiCard label={t("modules:maintenance.servicesCompletedMonth")} value={summary.services_completed_this_month} href="/services/overview" />
            <MaintenanceKpiCard label={t("modules:maintenance.upcomingReminders")} value={summary.upcoming_reminders_count} href="/services/reminders" />
            <MaintenanceKpiCard label={t("modules:maintenance.overdueReminders")} value={summary.overdue_reminders_count} href="/services/reminders?overdue_only=true" tone="danger" />
            <MaintenanceKpiCard label={t("modules:maintenance.failedInspections")} value={summary.failed_inspections_count} href="/inspections?overall_status=Failed" tone="danger" />
            <MaintenanceKpiCard label={t("modules:maintenance.inspectionsNeedingReview")} value={summary.inspections_needing_review_count} href="/inspections?overall_status=Needs+Review" tone="warning" />
            <MaintenanceKpiCard label={t("modules:maintenance.monthlyCost")} value={formatCurrency(summary.monthly_maintenance_cost)} />
          </div>

          <div className="maintenanceSections spaced">
            <RecordSection title={t("modules:maintenance.criticalWorkOrders")} items={summary.critical_work_orders} empty={t("modules:maintenance.empty")} />
            <RecordSection title={t("modules:maintenance.overdueWorkOrders")} items={summary.overdue_work_orders} empty={t("modules:maintenance.empty")} />
            <RecordSection title={t("modules:maintenance.overdueReminders")} items={summary.overdue_service_reminders} empty={t("modules:maintenance.empty")} />
            <RecordSection title={t("modules:maintenance.failedInspections")} items={summary.failed_inspections} empty={t("modules:maintenance.empty")} />
            <RecordSection title={t("modules:maintenance.vehiclesInService")} items={summary.vehicles_in_service} empty={t("modules:maintenance.empty")} />
          </div>

          <h2>{t("modules:maintenance.recentActivity")}</h2>
          <div className="maintenanceSections">
            <RecordSection title={t("modules:maintenance.recentlyCreatedWorkOrders")} items={summary.recently_created_work_orders} empty={t("modules:maintenance.empty")} />
            <RecordSection title={t("modules:maintenance.recentlyCompletedWorkOrders")} items={summary.recently_completed_work_orders} empty={t("modules:maintenance.empty")} />
            <RecordSection title={t("modules:maintenance.recentServices")} items={summary.recent_services} empty={t("modules:maintenance.empty")} />
            <RecordSection title={t("modules:maintenance.recentInspections")} items={summary.recent_inspections} empty={t("modules:maintenance.empty")} />
          </div>
        </>
      )}
    </section>
  );
}
