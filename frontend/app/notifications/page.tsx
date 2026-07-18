"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPut, buildQuery } from "@/lib/api";
import type { Notification, NotificationPriority, NotificationStatus, PageResult } from "@/lib/types";
import { Pagination } from "@/components/maintenance/Maintenance";

function relatedHref(notification: Notification): string | null {
  const id = notification.entity_id;
  if (!id) return null;
  return {
    WorkOrder: `/work-orders/${id}`,
    VehicleService: `/services/${id}`,
    Inspection: `/inspections/${id}`,
    Vehicle: `/vehicles/${id}`,
    VehiclePaper: "/papers",
    Driver: "/drivers",
    VehicleReservation: "/reservations"
  }[notification.entity_type ?? ""] ?? null;
}

export default function NotificationsPage() {
  const [result, setResult] = useState<PageResult<Notification>>({ items: [], page: 1, page_size: 20, total: 0, pages: 0 });
  const [filters, setFilters] = useState({ status: "", priority: "", notification_type: "", from_date: "", to_date: "" });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (page = 1) => {
    setLoading(true); setError(null);
    try {
      setResult(await apiGet<PageResult<Notification>>(`/notifications${buildQuery({ ...filters, page, page_size: 20 })}`));
    } catch (err) { setError(err instanceof Error ? err.message : "Could not load notifications."); }
    finally { setLoading(false); }
  }, [filters]);

  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function transition(id: number, action: "read" | "resolve" | "dismiss") {
    try { await apiPut(`/notifications/${id}/${action}`, {}); await load(result.page); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not update notification."); }
  }

  return <section>
    <div className="header"><div><h1>Notifications</h1><p className="muted">Urgent fleet events and assigned work in one place.</p></div><button className="secondaryButton" type="button" onClick={async () => { await apiPut("/notifications/read-all", {}); await load(result.page); }}>Mark all as read</button></div>
    {error && <div className="error spaced">{error}</div>}
    <div className="card filtersGrid spaced">
      <select className="select" value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}><option value="">All statuses</option>{(["Unread", "Read", "Resolved", "Dismissed"] as NotificationStatus[]).map((value) => <option key={value}>{value}</option>)}</select>
      <select className="select" value={filters.priority} onChange={(e) => setFilters({ ...filters, priority: e.target.value })}><option value="">All priorities</option>{(["Low", "Medium", "High", "Critical"] as NotificationPriority[]).map((value) => <option key={value}>{value}</option>)}</select>
      <input className="input" placeholder="Notification type" value={filters.notification_type} onChange={(e) => setFilters({ ...filters, notification_type: e.target.value })} />
      <button className="button" type="button" onClick={() => void load(1)}>Apply filters</button>
    </div>
    {loading ? <div className="card">Loading notifications...</div> : <div className="recordList card">
      {result.items.map((notification) => {
        const href = relatedHref(notification);
        return <div className="recordRow" key={notification.id}>
          <div><div className="recordTitle"><strong>{notification.title}</strong><span className={notification.priority === "Critical" ? "dangerBadge" : notification.priority === "High" ? "warningBadge" : "badge"}>{notification.priority}</span><span className="badge">{notification.status}</span></div><p>{notification.message}</p><span className="muted">{notification.notification_type} · {new Date(notification.created_at).toLocaleString()}</span></div>
          <div className="actions">{href && <Link className="secondaryButton smallButton" href={href}>Open record</Link>}{notification.status === "Unread" && <button className="secondaryButton smallButton" onClick={() => void transition(notification.id, "read")}>Mark read</button>}<button className="secondaryButton smallButton" onClick={() => void transition(notification.id, "resolve")}>Resolve</button><button className="secondaryButton smallButton" onClick={() => void transition(notification.id, "dismiss")}>Dismiss</button></div>
        </div>;
      })}
      {!result.items.length && <div className="maintenanceEmpty muted">No notifications match these filters.</div>}
    </div>}
    <Pagination page={result.page} pages={result.pages} total={result.total} onPageChange={(page) => void load(page)} />
  </section>;
}
