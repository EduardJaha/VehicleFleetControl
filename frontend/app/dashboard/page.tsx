"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import { AttentionRequired, FleetKpis } from "@/components/dashboard/FleetAndAttention";
import { DashboardFilters, type DashboardFilterState } from "@/components/dashboard/DashboardFilters";
import { ActiveUsageCard, OperationalPanels } from "@/components/dashboard/OperationsPanels";
import { FleetCostCard, FleetHealthCard, RecentActivity } from "@/components/dashboard/CostsAndActivity";
import { DashboardSkeleton, QuickActions } from "@/components/dashboard/QuickActions";
import { useAuth } from "@/lib/auth";
import { apiGet, buildQuery } from "@/lib/api";
import type { DashboardOverview } from "@/lib/types";

const EMPTY_OPTIONS = { locations: [], departments: [], cost_centers: [] };

function initialFilters(searchParams: URLSearchParams): DashboardFilterState {
  const requestedPeriod = searchParams.get("period") ?? "this_month";
  const completeCustomRange = Boolean(searchParams.get("from_date") && searchParams.get("to_date"));
  return {
    period: ["today", "last_7_days", "this_month", "last_month", "this_quarter", "this_year", "custom"].includes(requestedPeriod) && (requestedPeriod !== "custom" || completeCustomRange) ? requestedPeriod : "this_month",
    fromDate: searchParams.get("from_date") ?? "",
    toDate: searchParams.get("to_date") ?? "",
    locationId: searchParams.get("location_id") ?? "",
    departmentId: searchParams.get("department_id") ?? "",
    costCenterId: searchParams.get("cost_center_id") ?? ""
  };
}

function DashboardContent() {
  const { t } = useTranslation(["modules", "common"]);
  const { formatDate, formatDateTime } = useLanguage();
  const { user } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [filters, setFilters] = useState<DashboardFilterState>(() => initialFilters(searchParams));
  const [data, setData] = useState<DashboardOverview | null>(null);
  const dataRef = useRef<DashboardOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const query = useMemo(() => buildQuery({
    period: filters.period,
    from_date: filters.period === "custom" ? filters.fromDate : undefined,
    to_date: filters.period === "custom" ? filters.toDate : undefined,
    location_id: filters.locationId,
    department_id: filters.departmentId,
    cost_center_id: filters.costCenterId
  }), [filters]);

  const load = useCallback(async (background = false) => {
    if (filters.period === "custom" && (!filters.fromDate || !filters.toDate)) return;
    background ? setRefreshing(true) : setLoading(true);
    setError(null);
    try {
      const overview = await apiGet<DashboardOverview>(`/dashboard/overview${query}`);
      dataRef.current = overview;
      setData(overview);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:dashboard.loadError"));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [filters.fromDate, filters.period, filters.toDate, query, t]);

  useEffect(() => {
    router.replace(`/dashboard${query}`, { scroll: false });
    const timer = window.setTimeout(() => void load(Boolean(dataRef.current)), 180);
    return () => window.clearTimeout(timer);
  }, [load, query, router]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") void load(true);
    }, 60_000);
    return () => window.clearInterval(interval);
  }, [load]);

  const hour = new Date().getHours();
  const greeting = hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";

  return <section className="dashboardPage">
    <header className="dashboardHeader">
      <div>
        <p className="dashboardEyebrow">{t("modules:dashboard.workspace")}</p>
        <h1>{t(`modules:dashboard.greeting.${greeting}`, { name: user?.full_name?.split(" ")[0] ?? "" })}</h1>
        <p className="muted">{data ? t("modules:dashboard.range", { from: formatDate(data.filters.from_date), to: formatDate(data.filters.to_date) }) : t("modules:dashboard.description")}</p>
      </div>
      <div className="dashboardRefresh">
        {data && <span>{t("modules:dashboard.lastUpdated", { date: formatDateTime(data.generated_at) })}</span>}
        <button className="secondaryButton" type="button" disabled={loading || refreshing} onClick={() => void load(true)}>
          <span className={refreshing ? "refreshSpinner" : ""} aria-hidden="true">↻</span> {refreshing ? t("modules:dashboard.refreshing") : t("common:actions.refresh")}
        </button>
      </div>
    </header>

    <DashboardFilters value={filters} options={data?.filter_options ?? EMPTY_OPTIONS} disabled={loading && !data} onChange={setFilters} />
    <QuickActions />

    {error && <div className="error dashboardLoadError" role="alert"><span>{error}</span><button className="secondaryButton smallButton" type="button" onClick={() => void load(Boolean(data))}>{t("modules:dashboard.retry")}</button></div>}
    {loading && !data ? <DashboardSkeleton /> : !data ? <div className="card dashboardEmpty"><p>{t("modules:dashboard.loadError")}</p></div> : <div className={refreshing ? "dashboardRefreshing dashboardContent" : "dashboardContent"}>
      <FleetKpis fleet={data.fleet} />
      <AttentionRequired items={data.attention} total={data.attention_total} />
      <OperationalPanels data={data} />
      {data.usage && <ActiveUsageCard usage={data.usage} />}
      {(data.costs || data.fleet_health) && <div className="dashboardPanelGrid dashboardFinancialGrid">
        {data.costs && <FleetCostCard costs={data.costs} />}
        {data.fleet_health && <FleetHealthCard health={data.fleet_health} />}
      </div>}
      {data.recent_activity && <RecentActivity items={data.recent_activity} />}
    </div>}
  </section>;
}

export default function DashboardPage() {
  return <Suspense fallback={<DashboardSkeleton />}><DashboardContent /></Suspense>;
}
