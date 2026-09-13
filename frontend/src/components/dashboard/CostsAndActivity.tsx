"use client";

import Link from "next/link";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import type { DashboardOverview } from "@/lib/types";
import { DashboardCard, Metric } from "./DashboardCard";

type CostKey = "total" | "fuel" | "maintenance" | "accidents";

export function FleetCostCard({ costs }: { costs: NonNullable<DashboardOverview["costs"]> }) {
  const { t } = useTranslation(["modules", "common"]);
  const { formatCurrency } = useLanguage();
  const [metric, setMetric] = useState<CostKey>("total");
  const maximum = Math.max(...costs.trend.map((row) => row[metric]), 1);
  return <DashboardCard title={t("modules:dashboard.costs.title")} description={t("modules:dashboard.costs.description")} href="/reports/tco" actionLabel={t("common:actions.viewAll")} className="dashboardCostCard">
    <div className="costHeadline">
      <div><span>{t("modules:dashboard.costs.total")}</span><strong>{formatCurrency(costs.total)}</strong></div>
      {costs.change_percentage !== null && costs.change_percentage !== undefined && <span className={costs.change_percentage > 0 ? "dangerBadge" : "successBadge"}>{costs.change_percentage > 0 ? "↑" : "↓"} {Math.abs(costs.change_percentage)}% {t("modules:dashboard.costs.vsPrevious")}</span>}
    </div>
    <div className="costBreakdown">
      <Metric label={t("modules:dashboard.costs.fuel")} value={formatCurrency(costs.fuel)} />
      <Metric label={t("modules:dashboard.costs.charging")} value={formatCurrency(costs.charging)} />
      <Metric label={t("modules:dashboard.costs.maintenance")} value={formatCurrency(costs.maintenance)} />
      <Metric label={t("modules:dashboard.costs.accidents")} value={formatCurrency(costs.accidents)} />
      <Metric label={t("modules:dashboard.costs.other")} value={formatCurrency(costs.other)} />
    </div>
    <div className="costChartToolbar">
      <label>{t("modules:dashboard.costs.chartMetric")} <select className="select compactInput" value={metric} onChange={(event) => setMetric(event.target.value as CostKey)}>
        {(["total", "fuel", "maintenance", "accidents"] as CostKey[]).map((key) => <option key={key} value={key}>{t(`modules:dashboard.costs.${key}`)}</option>)}
      </select></label>
    </div>
    <div className="dashboardCostChart" role="img" aria-label={t("modules:dashboard.costs.chartLabel", { metric: t(`modules:dashboard.costs.${metric}`) })}>
      {costs.trend.map((row) => <div className="dashboardCostBarColumn" key={row.period} title={`${row.period}: ${formatCurrency(row[metric])}`}>
        <span className="dashboardCostBarValue">{formatCurrency(row[metric])}</span>
        <div className="dashboardCostBarTrack"><i style={{ height: `${Math.max((row[metric] / maximum) * 100, row[metric] ? 3 : 0)}%` }} /></div>
        <span>{row.period}</span>
      </div>)}
    </div>
    <table className="visuallyHidden"><caption>{t("modules:dashboard.costs.chartTable")}</caption><thead><tr><th>{t("modules:dashboard.filters.period")}</th><th>{t(`modules:dashboard.costs.${metric}`)}</th></tr></thead><tbody>{costs.trend.map((row) => <tr key={row.period}><td>{row.period}</td><td>{formatCurrency(row[metric])}</td></tr>)}</tbody></table>
  </DashboardCard>;
}

export function FleetHealthCard({ health }: { health: NonNullable<DashboardOverview["fleet_health"]> }) {
  const { t } = useTranslation(["modules", "common"]);
  const { formatCurrency, formatNumber } = useLanguage();
  return <DashboardCard title={t("modules:dashboard.health.title")} description={t("modules:dashboard.health.description")} href="/reports/tco" actionLabel={t("common:actions.viewAll")}>
    <div className="dashboardMetricGrid compact">
      <Metric label={t("modules:dashboard.health.replace")} value={health.replace} tone={health.replace ? "danger" : undefined} />
      <Metric label={t("modules:dashboard.health.replaceSoon")} value={health.replace_soon} tone={health.replace_soon ? "warning" : undefined} />
      <Metric label={t("modules:dashboard.health.highCost")} value={health.high_cost} />
      <Metric label={t("modules:dashboard.health.anomalies")} value={health.anomalies} />
    </div>
    <div className="dashboardCompactList">
      {health.candidates.map((vehicle) => <Link key={vehicle.vehicle_id} href={`/vehicles/${vehicle.vehicle_id}`}>
        <span><strong>{vehicle.license_plate}</strong><small>{vehicle.vehicle} · {formatNumber(vehicle.downtime_days)} {t("modules:dashboard.units.days")}</small></span>
        <span><span className={vehicle.status === "Replace" ? "dangerBadge" : "warningBadge"}>{t(`modules:dashboard.health.status.${vehicle.status.replace(" ", "")}`)}</span>{vehicle.cost_per_km !== null && vehicle.cost_per_km !== undefined && <small>{formatCurrency(vehicle.cost_per_km)}/{t("modules:dashboard.units.km")}</small>}</span>
      </Link>)}
      {!health.candidates.length && <p className="muted dashboardEmptyText">{t("modules:dashboard.health.empty")}</p>}
    </div>
  </DashboardCard>;
}

export function RecentActivity({ items }: { items: NonNullable<DashboardOverview["recent_activity"]> }) {
  const { t } = useTranslation(["modules", "common"]);
  const { formatDateTime } = useLanguage();
  return <DashboardCard title={t("modules:dashboard.activity.title")} href="/audit-logs" actionLabel={t("common:actions.viewAll")}>
    {!items.length ? <p className="muted dashboardEmptyText">{t("modules:dashboard.activity.empty")}</p> : <ol className="activityTimeline">
      {items.map((item) => <li key={item.id}><span className="activityDot" aria-hidden="true" /><div>{item.url ? <Link href={item.url}>{t(`modules:${item.action_key}`, item.params)}</Link> : <strong>{t(`modules:${item.action_key}`, item.params)}</strong>}<small>{formatDateTime(item.occurred_at)}</small></div></li>)}
    </ol>}
  </DashboardCard>;
}
