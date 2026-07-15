"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import type { MaintenanceTimelineEvent, UserRole } from "@/lib/types";

export const MAINTENANCE_LINKS: Array<{ href: string; label: string; roles: UserRole[] }> = [
  { href: "/maintenance", label: "Dashboard", roles: ["admin", "fleet_manager", "mechanic", "finance", "viewer"] },
  { href: "/work-orders", label: "Work Orders", roles: ["admin", "fleet_manager", "mechanic", "finance", "viewer"] },
  { href: "/services/overview", label: "Service History", roles: ["admin", "fleet_manager", "mechanic", "finance", "viewer"] },
  { href: "/services/reminders", label: "Service Reminders", roles: ["admin", "fleet_manager", "mechanic", "viewer"] },
  { href: "/inspections", label: "Inspections", roles: ["admin", "fleet_manager", "mechanic", "driver", "viewer"] }
];

export function MaintenanceNavigation() {
  const pathname = usePathname();
  const { user } = useAuth();
  if (!user) return null;
  return (
    <nav className="maintenanceTabs" aria-label="Maintenance sections">
      {MAINTENANCE_LINKS.filter((item) => item.roles.includes(user.role)).map((item) => (
        <Link key={item.href} href={item.href} className={pathname === item.href || (item.href !== "/maintenance" && pathname.startsWith(`${item.href}/`)) ? "maintenanceTab active" : "maintenanceTab"}>
          {item.label}
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
  const className = dangerStatuses.has(status) ? "dangerBadge" : warningStatuses.has(status) ? "warningBadge" : successStatuses.has(status) ? "successBadge" : "badge";
  return <span className={className}>{status}</span>;
}

export function MaintenancePriorityBadge({ priority }: { priority?: string | null }) {
  if (!priority) return <span className="muted">-</span>;
  const className = priority === "Critical" ? "dangerBadge" : priority === "High" ? "warningBadge" : "badge";
  return <span className={className}>{priority}</span>;
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
  return (
    <div className="pagination">
      <span className="muted">{total} record(s) · Page {page} of {Math.max(pages, 1)}</span>
      <div className="actions">
        <button className="secondaryButton smallButton" type="button" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>Previous</button>
        <button className="secondaryButton smallButton" type="button" disabled={page >= pages} onClick={() => onPageChange(page + 1)}>Next</button>
      </div>
    </div>
  );
}

export function LinkedRecordCard({ title, description, href, empty }: { title: string; description?: string | null; href?: string; empty?: string }) {
  return (
    <div className="linkedRecordCard">
      <strong>{title}</strong>
      {description && <span className="muted">{description}</span>}
      {href ? <Link className="secondaryButton smallButton" href={href}>View record</Link> : <span className="muted">{empty ?? "No linked record."}</span>}
    </div>
  );
}

export function MaintenanceTimeline({ events }: { events: MaintenanceTimelineEvent[] }) {
  if (!events.length) return <MaintenanceEmptyState>No maintenance timeline events have been recorded for this vehicle.</MaintenanceEmptyState>;
  return (
    <div className="timeline">
      {events.map((event) => (
        <article className="timelineItem" key={event.id}>
          <div className="timelineMarker" />
          <div className="timelineContent">
            <time>{new Date(event.occurred_at).toLocaleString()}</time>
            <div className="timelineTitle"><strong>{event.event_type}</strong>{event.status && <MaintenanceStatusBadge status={event.status} />}{event.priority && <MaintenancePriorityBadge priority={event.priority} />}</div>
            <div>{event.title}</div>
            {event.description && <p className="muted">{event.description}</p>}
            <div className="timelineMeta">{event.actor && <span>Actor: {event.actor}</span>}<Link className="link" href={event.href}>{event.related_record_type} #{event.related_record_id}</Link></div>
          </div>
        </article>
      ))}
    </div>
  );
}

export function formatMoney(value?: string | number | null) {
  if (value === null || value === undefined || value === "") return "-";
  return new Intl.NumberFormat(undefined, { style: "currency", currency: "EUR" }).format(Number(value));
}
