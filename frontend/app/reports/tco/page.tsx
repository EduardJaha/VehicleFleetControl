"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { apiDownload, apiGet, buildQuery } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import { toApiDate } from "@/lib/format";

type TcoRow = {
  vehicle_id: number; license_plate: string; vehicle: string; ownership_type: string;
  total_cost: number; cost_per_km: number | null; distance_km: number | null;
  downtime_days: number; maintenance_frequency_per_year: number; current_book_value: number | null;
  recommendation_status: "Retain" | "Monitor" | "Replace Soon" | "Replace";
  recommendation_reasons: string[]; anomaly_count: number;
  efficiency: { liters_per_100_km: number | null; kwh_per_100_km: number | null; distance_between_refuels_km: number | null; insufficient_odometer_history: boolean };
};

type TcoReport = {
  kpis: Record<string, number | null>;
  cost_by_category: Record<string, number>;
  monthly_trend: Array<{ month: string; total_cost: number }>;
  rows: TcoRow[];
  anomalies: Array<{ vehicle_id: number; record_id: number; type: string; severity: string }>;
  methodology: Record<string, unknown>;
};

const recommendationClass = { Retain: "successBadge", Monitor: "badge", "Replace Soon": "warningBadge", Replace: "dangerBadge" } as const;

function TcoContent() {
  const { t } = useTranslation(["modules", "common"]);
  const { can } = useAuth();
  const { formatCurrency, formatNumber } = useLanguage();
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const searchParams = useSearchParams();
  const [plate, setPlate] = useState(searchParams.get("license_plate") ?? "");
  const [report, setReport] = useState<TcoReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const query = useMemo(() => buildQuery({ from_date: toApiDate(fromDate), to_date: toApiDate(toDate), license_plate: plate }), [fromDate, plate, toDate]);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try { setReport(await apiGet<TcoReport>(`/reports/tco${query}`)); }
    catch (err) { setError(err instanceof Error ? err.message : t("modules:tco.loadError")); }
    finally { setLoading(false); }
  }, [query, t]);

  useEffect(() => { if (can("reportsRead")) void load(); }, [can, load]);
  if (!can("reportsRead")) return <div className="error">{t("modules:reports.accessDenied")}</div>;

  const categoryMax = Math.max(1, ...Object.values(report?.cost_by_category ?? {}));
  const trendMax = Math.max(1, ...(report?.monthly_trend.map((row) => row.total_cost) ?? []));
  return <section>
    <div className="header"><div><h1>{t("modules:tco.title")}</h1><p className="muted">{t("modules:tco.description")}</p></div><div className="actions"><Link className="secondaryButton" href="/reports">{t("modules:tco.allReports")}</Link><button className="button" onClick={() => void apiDownload(`/reports/tco/export${query}`, "vehicle-tco.xlsx")}>{t("common:actions.export")}</button></div></div>
    {error && <div className="error spaced">{error}</div>}
    <div className="card filtersGrid spaced"><input className="input" type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} /><input className="input" type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} /><input className="input" value={plate} onChange={(e) => setPlate(e.target.value)} placeholder={t("modules:reports.platePlaceholder")} /><button className="button" onClick={() => void load()}>{t("common:actions.applyFilters")}</button></div>
    {loading || !report ? <div className="card">{t("modules:reports.loading")}</div> : <>
      <div className="kpiGrid spaced">
        <div className="card"><div className="muted">{t("modules:tco.totalCost")}</div><h2>{formatCurrency(report.kpis.total_cost ?? 0)}</h2></div>
        <div className="card"><div className="muted">{t("modules:tco.averageCostKm")}</div><h2>{report.kpis.average_cost_per_km == null ? "–" : formatCurrency(report.kpis.average_cost_per_km)}</h2></div>
        <div className="card"><div className="muted">{t("modules:tco.downtime")}</div><h2>{formatNumber(report.kpis.total_downtime_days ?? 0)} d</h2></div>
        <div className="card"><div className="muted">{t("modules:tco.replacementCandidates")}</div><h2>{formatNumber(report.kpis.replacement_candidates ?? 0)}</h2></div>
      </div>
      <div className="tcoCharts spaced">
        <div className="card"><h2>{t("modules:tco.costByCategory")}</h2><div className="tcoBars">{Object.entries(report.cost_by_category).map(([key, value]) => <div className="tcoBarRow" key={key}><span>{t(`modules:tco.categories.${key}`)}</span><div className="tcoBarTrack"><span style={{ width: `${Math.max(1, value / categoryMax * 100)}%` }} /></div><strong>{formatCurrency(value)}</strong></div>)}</div></div>
        <div className="card"><h2>{t("modules:tco.monthlyTrend")}</h2><div className="tcoTrend">{report.monthly_trend.map((row) => <div className="tcoTrendItem" key={row.month} title={`${row.month}: ${formatCurrency(row.total_cost)}`}><div style={{ height: `${Math.max(3, row.total_cost / trendMax * 100)}%` }} /><span>{row.month.slice(2)}</span></div>)}</div></div>
      </div>
      {report.anomalies.length > 0 && <div className="card spaced"><h2>{t("modules:tco.anomalies")}</h2><div className="recordList">{report.anomalies.slice(0, 20).map((item, index) => { const vehicleRow = report.rows.find((row) => row.vehicle_id === item.vehicle_id); return <div className="recordRow" key={`${item.vehicle_id}-${item.record_id}-${item.type}-${index}`}><span><strong>{vehicleRow?.license_plate ?? `#${item.vehicle_id}`}</strong><span className="recordMeta">{t(`modules:tco.anomalyTypes.${item.type}`)} · #{item.record_id}</span></span><span className={item.severity === "critical" ? "dangerBadge" : "warningBadge"}>{item.severity}</span></div>; })}</div></div>}
      <div className="tableScroll"><table className="table"><thead><tr><th>{t("modules:tco.vehicle")}</th><th>{t("modules:tco.totalCost")}</th><th>{t("modules:tco.costKm")}</th><th>{t("modules:tco.efficiency")}</th><th>{t("modules:tco.downtime")}</th><th>{t("modules:tco.maintenanceFrequency")}</th><th>{t("modules:tco.bookValue")}</th><th>{t("modules:tco.recommendation")}</th></tr></thead><tbody>{report.rows.map((row) => <tr key={row.vehicle_id}><td><Link className="link" href={`/vehicles/${row.vehicle_id}`}>{row.license_plate}</Link><div className="muted">{row.vehicle} · {row.ownership_type}</div></td><td>{formatCurrency(row.total_cost)}</td><td>{row.cost_per_km == null ? t("modules:tco.insufficientHistory") : formatCurrency(row.cost_per_km)}</td><td>{row.efficiency.liters_per_100_km != null ? `${formatNumber(row.efficiency.liters_per_100_km)} L/100 km` : row.efficiency.kwh_per_100_km != null ? `${formatNumber(row.efficiency.kwh_per_100_km)} kWh/100 km` : "–"}<div className="muted">{row.efficiency.distance_between_refuels_km == null ? "" : `${formatNumber(row.efficiency.distance_between_refuels_km)} km`}</div></td><td>{formatNumber(row.downtime_days)} d</td><td>{formatNumber(row.maintenance_frequency_per_year)}/{t("modules:tco.year")}</td><td>{row.current_book_value == null ? "–" : formatCurrency(row.current_book_value)}</td><td><span className={recommendationClass[row.recommendation_status]}>{t(`modules:tco.status.${row.recommendation_status}`)}</span><div className="muted">{row.recommendation_reasons.map((reason) => t(`modules:tco.reasons.${reason}`)).join(" · ")}</div></td></tr>)}</tbody></table></div>
      <div className="card"><h2>{t("modules:tco.rulesTitle")}</h2><p className="muted">{t("modules:tco.rulesDescription")}</p></div>
    </>}
  </section>;
}

export default function TcoPage() {
  return <Suspense fallback={<div className="card">Loading…</div>}><TcoContent /></Suspense>;
}
