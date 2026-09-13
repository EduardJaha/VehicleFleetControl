"use client";

import Link from "next/link";
import type { CSSProperties } from "react";
import { useTranslation } from "react-i18next";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import type { DashboardOverview } from "@/lib/types";
import { DashboardCard, Metric } from "./DashboardCard";

type Props = { data: DashboardOverview };

export function OperationalPanels({ data }: Props) {
  const { t } = useTranslation(["modules", "common"]);
  return (
    <div className="dashboardPanelGrid">
      {data.maintenance && <DashboardCard title={t("modules:dashboard.maintenance.title")} href="/maintenance" actionLabel={t("common:actions.viewAll")}>
        <div className="dashboardMetricGrid">
          <Metric label={t("modules:dashboard.maintenance.openWorkOrders")} value={data.maintenance.open_work_orders} />
          <Metric label={t("modules:dashboard.maintenance.critical")} value={data.maintenance.critical_work_orders} tone={data.maintenance.critical_work_orders ? "danger" : undefined} />
          <Metric label={t("modules:dashboard.maintenance.overdue")} value={data.maintenance.overdue_work_orders} tone={data.maintenance.overdue_work_orders ? "warning" : undefined} />
          <Metric label={t("modules:dashboard.maintenance.waitingParts")} value={data.maintenance.waiting_for_parts} />
          <Metric label={t("modules:dashboard.maintenance.vehiclesInService")} value={data.maintenance.vehicles_in_service} />
          <Metric label={t("modules:dashboard.maintenance.failedInspections")} value={data.maintenance.failed_inspections} tone={data.maintenance.failed_inspections ? "danger" : undefined} />
        </div>
      </DashboardCard>}

      {data.compliance && <DashboardCard title={t("modules:dashboard.compliance.title")} href="/compliance/documents" actionLabel={t("common:actions.viewAll")}>
        <div className="complianceGauge" style={{ "--dashboard-progress": `${Math.min(data.compliance.percentage, 100)}%` } as CSSProperties}>
          <strong>{data.compliance.percentage}%</strong><span>{t("modules:dashboard.compliance.compliant")}</span>
        </div>
        <div className="dashboardMetricGrid compact">
          <Metric label={t("modules:dashboard.compliance.missing")} value={data.compliance.missing_required} tone={data.compliance.missing_required ? "danger" : undefined} />
          <Metric label={t("modules:dashboard.compliance.expired")} value={data.compliance.expired} tone={data.compliance.expired ? "danger" : undefined} />
          <Metric label={t("modules:dashboard.compliance.expiring7")} value={data.compliance.expiring_7_days} tone={data.compliance.expiring_7_days ? "warning" : undefined} />
          <Metric label={t("modules:dashboard.compliance.renewing")} value={data.compliance.renewal_in_progress} />
        </div>
      </DashboardCard>}

      {data.reservations && <DashboardCard title={t("modules:dashboard.reservations.title")} href="/reservations" actionLabel={t("common:actions.viewAll")}>
        <div className="dashboardMetricGrid compact">
          <Metric label={t("modules:dashboard.reservations.pending")} value={data.reservations.pending} tone={data.reservations.pending ? "warning" : undefined} />
          <Metric label={t("modules:dashboard.reservations.approvedToday")} value={data.reservations.approved_today} />
          <Metric label={t("modules:dashboard.reservations.startingToday")} value={data.reservations.starting_today} />
        </div>
        <div className="dashboardCompactList">
          {data.reservations.records.slice(0, 4).map((reservation) => <Link key={reservation.id} href="/reservations">
            <span><strong>{reservation.license_plate}</strong><small>{reservation.reserved_by}</small></span>
            <span className={reservation.status === 0 ? "warningBadge" : "successBadge"}>{t(`common:status.${reservation.status_name}`)}</span>
          </Link>)}
          {!data.reservations.records.length && <p className="muted dashboardEmptyText">{t("modules:dashboard.reservations.empty")}</p>}
        </div>
      </DashboardCard>}

      {data.safety && <SafetyCard safety={data.safety} />}
    </div>
  );
}

function SafetyCard({ safety }: { safety: NonNullable<DashboardOverview["safety"]> }) {
  const { t } = useTranslation(["modules", "common"]);
  const { formatCurrency } = useLanguage();
  return <DashboardCard title={t("modules:dashboard.safety.title")} href="/accidents" actionLabel={t("common:actions.viewAll")}>
    <div className="dashboardMetricGrid compact">
      <Metric label={t("modules:dashboard.safety.periodAccidents")} value={safety.accidents_period} />
      <Metric label={t("modules:dashboard.safety.openAccidents")} value={safety.open_accidents} tone={safety.open_accidents ? "danger" : undefined} />
      <Metric label={t("modules:dashboard.safety.openClaims")} value={safety.open_claims} tone={safety.open_claims ? "warning" : undefined} />
      <Metric label={t("modules:dashboard.safety.unavailable")} value={safety.vehicles_unavailable} />
    </div>
    {safety.damage_cost !== null && safety.damage_cost !== undefined && <div className="safetyCosts">
      <span>{t("modules:dashboard.safety.damage")} <strong>{formatCurrency(safety.damage_cost)}</strong></span>
      <span>{t("modules:dashboard.safety.recovered")} <strong>{formatCurrency(safety.recovered_cost)}</strong></span>
      <span>{t("modules:dashboard.safety.unrecovered")} <strong>{formatCurrency(safety.unrecovered_cost)}</strong></span>
    </div>}
  </DashboardCard>;
}

function duration(minutes: number, hour: string, minute: string) {
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return hours ? `${hours}${hour} ${remainder}${minute}` : `${remainder}${minute}`;
}

export function ActiveUsageCard({ usage }: { usage: NonNullable<DashboardOverview["usage"]> }) {
  const { t } = useTranslation(["modules", "common"]);
  const { formatDateTime } = useLanguage();
  return <DashboardCard title={t("modules:dashboard.usage.title")} description={t("modules:dashboard.usage.description")} href="/vehicle-assignments?active_only=true" actionLabel={t("common:actions.viewAll")}>
    <div className="usageSummary"><strong>{usage.active_count}</strong> {t("modules:dashboard.usage.active")} {usage.overdue_returns > 0 && <span className="dangerBadge">{t("modules:dashboard.usage.overdueCount", { count: usage.overdue_returns })}</span>}</div>
    {!usage.records.length ? <div className="dashboardEmpty"><span aria-hidden="true">✓</span><p>{t("modules:dashboard.usage.empty")}</p></div> : <div className="tableScroll">
      <table className="table dashboardUsageTable">
        <thead><tr><th>{t("common:labels.vehicle")}</th><th>{t("common:labels.driver")}</th><th>{t("modules:dashboard.usage.checkedOut")}</th><th>{t("modules:dashboard.usage.expected")}</th><th>{t("modules:dashboard.usage.duration")}</th><th>{t("common:labels.status")}</th></tr></thead>
        <tbody>{usage.records.map((record) => <tr key={record.assignment_id} className={record.overdue ? "overdueRow" : ""}>
          <td><Link className="link" href={`/vehicle-assignments/${record.assignment_id}`}>{record.license_plate}</Link><small>{record.vehicle_name}</small></td>
          <td><Link className="link" href={`/drivers/${record.driver_id}`}>{record.driver_name}</Link></td>
          <td>{formatDateTime(record.checkout_datetime)}</td><td>{record.expected_return_datetime ? formatDateTime(record.expected_return_datetime) : "—"}</td>
          <td>{duration(record.duration_minutes, t("modules:dashboard.units.hour"), t("modules:dashboard.units.minute"))}</td>
          <td><span className={record.overdue ? "dangerBadge" : "successBadge"}>{record.overdue ? t("modules:dashboard.usage.overdueBy", { duration: duration(record.overdue_minutes, t("modules:dashboard.units.hour"), t("modules:dashboard.units.minute")) }) : t("modules:dashboard.usage.onTime")}</span></td>
        </tr>)}</tbody>
      </table>
    </div>}
  </DashboardCard>;
}
