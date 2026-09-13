"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/lib/auth";

const ACTIONS = [
  { permission: "vehicles.create", href: "/vehicles/new", key: "vehicle", icon: "+" },
  { permission: "assignments.manage", href: "/vehicle-assignments?checkout=1", key: "checkout", icon: "↗" },
  { permission: "fuel.create", href: "/fuel", key: "fuel", icon: "◉" },
  { permission: "inspections.create", href: "/inspections", key: "inspection", icon: "✓" },
  { permission: "maintenance.create_work_order", href: "/work-orders", key: "workOrder", icon: "⚙" },
  { permission: "reservations.create", href: "/reservations", key: "reservation", icon: "▣" }
];

export function QuickActions() {
  const { t } = useTranslation("modules");
  const { can } = useAuth();
  const actions = ACTIONS.filter((action) => can(action.permission));
  if (!actions.length) return null;
  return <section className="dashboardQuickActions" aria-labelledby="quick-actions-title"><h2 id="quick-actions-title">{t("dashboard.quickActions.title")}</h2><div>
    {actions.map((action) => <Link key={action.key} href={action.href}><span aria-hidden="true">{action.icon}</span>{t(`dashboard.quickActions.${action.key}`)}</Link>)}
  </div></section>;
}

export function DashboardSkeleton() {
  return <div className="dashboardSkeleton" aria-hidden="true"><div className="skeletonFilters" /><div className="skeletonKpis">{Array.from({ length: 5 }, (_, index) => <i key={index} />)}</div><div className="skeletonPanels"><i /><i /><i /><i /></div></div>;
}
