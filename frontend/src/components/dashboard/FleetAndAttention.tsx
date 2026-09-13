"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import type { DashboardOverview } from "@/lib/types";
import { DashboardCard } from "./DashboardCard";

export function FleetKpis({ fleet }: { fleet: DashboardOverview["fleet"] }) {
  const { t } = useTranslation("modules");
  const items = [
    { key: "total", value: fleet.total, href: "/vehicles" },
    { key: "available", value: fleet.available, href: "/vehicles?status=0", tone: "success" },
    { key: "inUse", value: fleet.in_use, href: "/vehicle-assignments?active_only=true" },
    { key: "inService", value: fleet.in_service, href: "/vehicles?status=1", tone: "warning" },
    { key: "unavailable", value: fleet.unavailable, href: "/vehicles", tone: "danger" }
  ];
  return (
    <section aria-labelledby="fleet-kpis-title">
      <div className="dashboardSectionHeading">
        <div><h2 id="fleet-kpis-title">{t("dashboard.fleet.title")}</h2><p className="muted">{t("dashboard.fleet.description")}</p></div>
        <div className="availabilitySummary" aria-label={t("dashboard.fleet.availability")}>{fleet.availability_percentage}% <span>{t("dashboard.fleet.availability")}</span></div>
      </div>
      <div className="dashboardKpiGrid">
        {items.map((item) => <Link key={item.key} href={item.href} className={`dashboardKpi dashboardKpi-${item.tone ?? "neutral"}`}>
          <span>{t(`dashboard.fleet.${item.key}`)}</span><strong>{item.value}</strong><small>{t("dashboard.openDetails")} →</small>
        </Link>)}
      </div>
    </section>
  );
}

export function AttentionRequired({ items, total }: { items: DashboardOverview["attention"]; total: number }) {
  const { t } = useTranslation(["modules", "common"]);
  const { formatDateTime } = useLanguage();
  return (
    <DashboardCard title={t("modules:dashboard.attention.title")} description={t("modules:dashboard.attention.description")} href="/notifications" actionLabel={t("common:actions.viewAll")} className="dashboardAttentionCard">
      {!items.length ? <div className="dashboardEmpty"><span aria-hidden="true">✓</span><p>{t("modules:dashboard.attention.empty")}</p></div> : <div className="attentionList">
        {items.map((item) => <Link key={item.id} href={item.url} className="attentionItem">
          <span className={`attentionPriority attentionPriority-${item.priority.toLowerCase()}`}>{t(`modules:dashboard.priorities.${item.priority}`)}</span>
          <div><strong>{t(`modules:${item.title_key}`)}</strong><p>{t(`modules:${item.message_key}`, item.params)}</p><small>{formatDateTime(item.due_at ?? item.occurred_at)}</small></div>
          <span aria-hidden="true">›</span>
        </Link>)}
      </div>}
      {total > items.length && <p className="dashboardListFootnote">{t("modules:dashboard.attention.more", { count: total - items.length })}</p>}
    </DashboardCard>
  );
}
