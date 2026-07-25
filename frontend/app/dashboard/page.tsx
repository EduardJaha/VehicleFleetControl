"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import { apiGet } from "@/lib/api";
import type { DashboardSummary } from "@/lib/types";
import { VEHICLE_STATUS_KEYS } from "@/lib/constants";

export default function DashboardPage() {
  const { t } = useTranslation(["modules", "common"]);
  const { formatDateTime } = useLanguage();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadDashboard() {
      setLoading(true);
      setError(null);
      try {
        setSummary(await apiGet<DashboardSummary>("/dashboard/summary"));
      } catch (err) {
        setError(err instanceof Error ? err.message : t("modules:dashboard.loadError"));
      } finally {
        setLoading(false);
      }
    }
    void loadDashboard();
  }, []);

  return (
    <section>
      <div className="header">
        <div>
          <h1>{t("modules:dashboard.title")}</h1>
          <p className="muted">{t("modules:dashboard.description")}</p>
        </div>
      </div>

      {error && <div className="error spaced">{error}</div>}
      {loading ? (
        <div className="card">{t("modules:dashboard.loading")}</div>
      ) : !summary ? (
        <div className="error">{t("modules:dashboard.loadError")}</div>
      ) : (
        <>
        <div className="grid cols-3">
          <div className="card">
            <div className="muted">{t("modules:dashboard.totalVehicles")}</div>
            <h2>{summary.total_vehicles}</h2>
            <p>{t("modules:dashboard.activeUsageCount")}: <strong>{summary.active_usage_count}</strong></p>
            <p>{t("modules:dashboard.overdueReturns")}: <strong>{summary.overdue_return_count}</strong></p>
          </div>
          <div className="card">
            <div className="muted">{t("modules:dashboard.byStatus")}</div>
            {summary.status_summary.map((item) => (
              <p key={item.status}>{VEHICLE_STATUS_KEYS[item.status] ? t(`common:${VEHICLE_STATUS_KEYS[item.status]}`) : item.status}: <strong>{item.count}</strong></p>
            ))}
          </div>
          <div className="card">
            <div className="muted">{t("modules:dashboard.byLocation")}</div>
            {summary.location_summary.map((item) => (
              <p key={item.location}>{item.location}: <strong>{item.count}</strong></p>
            ))}
          </div>
        </div>
        <section className="card spaced">
          <h2>{t("modules:dashboard.activeUsage")}</h2>
          {summary.active_usage.length === 0 ? <p className="muted">{t("modules:dashboard.noActiveUsage")}</p> : (
            <div className="tableScroll">
              <table className="table">
                <thead><tr><th>{t("common:labels.vehicle")}</th><th>{t("common:labels.driver")}</th><th>{t("modules:dashboard.checkedOutAt")}</th><th>{t("modules:dashboard.expectedReturn")}</th><th>{t("modules:vehicleAssignments.destination")}</th><th>{t("common:labels.status")}</th></tr></thead>
                <tbody>{summary.active_usage.map((usage) => (
                  <tr key={usage.assignment_id}>
                    <td><Link className="link" href={`/vehicle-assignments/${usage.assignment_id}`}>{usage.license_plate}</Link><div className="muted">{usage.vehicle_name}</div></td>
                    <td><Link className="link" href={`/drivers/${usage.driver_id}`}>{usage.driver_name}</Link></td>
                    <td>{formatDateTime(usage.checkout_datetime)}</td>
                    <td>{usage.expected_return_datetime ? formatDateTime(usage.expected_return_datetime) : "—"}</td>
                    <td>{usage.destination ?? "—"}</td>
                    <td><span className={usage.overdue ? "warningBadge" : "successBadge"}>{usage.overdue ? t("modules:dashboard.overdueReturns") : t("common:status.Active")}</span></td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </section>
        </>
      )}
    </section>
  );
}
