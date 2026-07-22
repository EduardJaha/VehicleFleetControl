"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import type { MaintenanceTimelineEvent, UserRole } from "@/lib/types";
import { useTranslation } from "react-i18next";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import { translateNotification, translateStatus, translateType } from "@/i18n/translate";

export const MAINTENANCE_LINKS: Array<{ href: string; labelKey: string; roles: UserRole[] }> = [
  { href: "/maintenance", labelKey: "maintenanceDashboard", roles: ["admin", "fleet_manager", "mechanic", "finance", "viewer"] },
  { href: "/work-orders", labelKey: "workOrders", roles: ["admin", "fleet_manager", "mechanic", "finance", "viewer"] },
  { href: "/services/overview", labelKey: "serviceHistory", roles: ["admin", "fleet_manager", "mechanic", "finance", "viewer"] },
  { href: "/services/reminders", labelKey: "serviceReminders", roles: ["admin", "fleet_manager", "mechanic", "viewer"] },
  { href: "/inspections", labelKey: "inspections", roles: ["admin", "fleet_manager", "mechanic", "driver", "viewer"] }
];

export function MaintenanceNavigation() {
  const pathname = usePathname();
  const { user } = useAuth();
  const { t } = useTranslation(["navigation", "common"]);
  if (!user) return null;
  return (
    <nav className="maintenanceTabs" aria-label={t("navigation:maintenance")}>
      {MAINTENANCE_LINKS.filter((item) => item.roles.includes(user.role)).map((item) => (
        <Link key={item.href} href={item.href} className={pathname === item.href || (item.href !== "/maintenance" && pathname.startsWith(`${item.href}/`)) ? "maintenanceTab active" : "maintenanceTab"}>
          {t(`navigation:${item.labelKey}`)}
        </Link>
      ))}
    </nav>
  );
}

export function MaintenancePageHeader({ title, description, actions }: { title: string; description: string; actions?: ReactNode }) {
  return (
    <>
      <MaintenanceNavigation />
      <div className="header">
        <div><h1>{title}</h1><p className="muted">{description}</p></div>
        {actions && <div className="actions">{actions}</div>}
      </div>
    </>
  );
}

const successStatuses = new Set(["Completed", "Passed", "Resolved"]);
const warningStatuses = new Set(["Assigned", "Waiting for Parts", "Due Soon", "Due", "Needs Review", "Upcoming"]);
const dangerStatuses = new Set(["Failed", "Overdue", "Cancelled"]);

export function MaintenanceStatusBadge({ status }: { status: string }) {
  useTranslation("common");
  const className = dangerStatuses.has(status) ? "dangerBadge" : warningStatuses.has(status) ? "warningBadge" : successStatuses.has(status) ? "successBadge" : "badge";
  return <span className={className}>{translateStatus(status)}</span>;
}

export function MaintenancePriorityBadge({ priority }: { priority?: string | null }) {
  useTranslation("common");
  if (!priority) return <span className="muted">-</span>;
  const className = priority === "Critical" ? "dangerBadge" : priority === "High" ? "warningBadge" : "badge";
  return <span className={className}>{translateStatus(priority)}</span>;
}

export function MaintenanceKpiCard({ label, value, href, tone }: { label: string; value: ReactNode; href?: string; tone?: "danger" | "warning" }) {
  const card = <div className={`card maintenanceKpi ${tone ? `kpi-${tone}` : ""}`}><div className="kpiLabel">{label}</div><div className="kpiValue">{value}</div></div>;
  return href ? <Link href={href}>{card}</Link> : card;
}

export function MaintenanceEmptyState({ children }: { children: ReactNode }) {
  return <div className="maintenanceEmpty muted">{children}</div>;
}

export function MaintenanceTable({ children }: { children: ReactNode }) {
  return <div className="tableScroll"><table className="table">{children}</table></div>;
}

export function Pagination({ page, pages, total, onPageChange }: { page: number; pages: number; total: number; onPageChange: (page: number) => void }) {
  const { t } = useTranslation("common");
  return (
    <div className="pagination">
      <span className="muted">{t("states.records", { count: total })} · {t("states.page", { page, pages: Math.max(pages, 1) })}</span>
      <div className="actions">
        <button className="secondaryButton smallButton" type="button" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>{t("actions.previous")}</button>
        <button className="secondaryButton smallButton" type="button" disabled={page >= pages} onClick={() => onPageChange(page + 1)}>{t("actions.next")}</button>
      </div>
    </div>
  );
}

export function LinkedRecordCard({ title, description, href, empty }: { title: string; description?: string | null; href?: string; empty?: string }) {
  const { t } = useTranslation("common");
  return (
    <div className="linkedRecordCard">
      <strong>{title}</strong>
      {description && <span className="muted">{description}</span>}
      {href ? <Link className="secondaryButton smallButton" href={href}>{t("actions.view")}</Link> : <span className="muted">{empty ?? t("states.noResults")}</span>}
    </div>
  );
}

export function MaintenanceTimeline({ events }: { events: MaintenanceTimelineEvent[] }) {
  const { t } = useTranslation(["modules", "common"]);
  const { formatDateTime } = useLanguage();
  if (!events.length) return <MaintenanceEmptyState>{t("common:states.noResults")}</MaintenanceEmptyState>;
  return (
    <div className="timeline">
      {events.map((event) => (
        <article className="timelineItem" key={event.id}>
          <div className="timelineMarker" />
          <div className="timelineContent">
            <time>{formatDateTime(event.occurred_at)}</time>
            <div className="timelineTitle"><strong>{event.event_code ? translateNotification(`modules:timeline.events.${event.event_code}`, event.params, event.event_type) : event.event_type}</strong>{event.status && <MaintenanceStatusBadge status={event.status} />}{event.priority && <MaintenancePriorityBadge priority={event.priority} />}</div>
            <div>{translateNotification(event.title_key, event.params, event.title)}</div>
            {event.description && <p className="muted">{translateNotification(event.description_key, event.params, event.description)}</p>}
            <div className="timelineMeta">{event.actor && <span>{t("common:labels.user")}: {event.actor}</span>}<Link className="link" href={event.href}>{translateType(event.related_record_type)} #{event.related_record_id}</Link></div>
          </div>
        </article>
      ))}
    </div>
  );
}
