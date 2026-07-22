"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiGet } from "@/lib/api";
import type { DashboardSummary } from "@/lib/types";
import { VEHICLE_STATUS_KEYS } from "@/lib/constants";

export default function DashboardPage() {
  const { t } = useTranslation(["modules", "common"]);
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
        <div className="grid cols-3">
          <div className="card">
            <div className="muted">{t("modules:dashboard.totalVehicles")}</div>
            <h2>{summary.total_vehicles}</h2>
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
      )}
    </section>
  );
}
