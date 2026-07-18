"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AuthProvider, ROLE_LABELS, useAuth } from "@/lib/auth";
import { MAINTENANCE_LINKS } from "@/components/maintenance/Maintenance";
import { apiGet } from "@/lib/api";
import type { Notification, PageResult } from "@/lib/types";

const navItems = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/vehicles", label: "Vehicles" },
  { href: "/drivers", label: "Drivers" },
  { href: "/reports", label: "Reports" },
  { href: "/papers", label: "Documents" },
  { href: "/fuel", label: "Fuel" },
  { href: "/accidents", label: "Accidents" },
  { href: "/reservations", label: "Reservations" }
];

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <ProtectedShell>{children}</ProtectedShell>
    </AuthProvider>
  );
}

function ProtectedShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, ready, logout } = useAuth();
  const isLoginPage = pathname === "/login";
  const maintenanceActive = pathname === "/maintenance" || pathname.startsWith("/work-orders") || pathname.startsWith("/services") || pathname.startsWith("/inspections");
  const [unreadCount, setUnreadCount] = useState(0);
  const [recentNotifications, setRecentNotifications] = useState<Notification[]>([]);
  const [notificationsOpen, setNotificationsOpen] = useState(false);

  const loadNotifications = useCallback(async () => {
    if (!user) return;
    try {
      const [count, recent] = await Promise.all([
        apiGet<{ unread_count: number }>("/notifications/unread-count"),
        apiGet<PageResult<Notification>>("/notifications?page=1&page_size=5")
      ]);
      setUnreadCount(count.unread_count);
      setRecentNotifications(recent.items);
    } catch {
      // Authentication failures are handled centrally by the API helper.
    }
  }, [user]);

  useEffect(() => {
    if (ready && !user && !isLoginPage) {
      router.replace("/login");
    }
  }, [isLoginPage, ready, router, user]);

  useEffect(() => {
    if (!user) return;
    void loadNotifications();
    const timer = window.setInterval(() => void loadNotifications(), 60_000);
    return () => window.clearInterval(timer);
  }, [loadNotifications, pathname, user]);

  if (isLoginPage) {
    return <>{children}</>;
  }

  if (!ready || !user) {
    return (
      <div className="authLoading">
        <div className="card">Loading session...</div>
      </div>
    );
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">Vehicle Fleet Control</div>
        <nav>
          {navItems.slice(0, 3).map((item) => <Link key={item.href} href={item.href} className={pathname === item.href ? "navLink active" : "navLink"}>{item.label}</Link>)}
          <details className="navGroup" open={maintenanceActive}>
            <summary className={maintenanceActive ? "navLink active" : "navLink"}>Maintenance</summary>
            <div className="navSubmenu">
              {MAINTENANCE_LINKS.filter((item) => item.roles.includes(user.role)).map((item) => (
                <Link key={item.href} href={item.href} className={pathname === item.href || (item.href !== "/maintenance" && pathname.startsWith(`${item.href}/`)) ? "navLink navSubLink active" : "navLink navSubLink"}>{item.label}</Link>
              ))}
            </div>
          </details>
          {navItems.slice(3).map((item) => <Link key={item.href} href={item.href} className={pathname === item.href ? "navLink active" : "navLink"}>{item.label}</Link>)}
          <Link href="/notifications" className={pathname === "/notifications" ? "navLink active" : "navLink"}>Notifications</Link>
          {user.role === "admin" && <Link href="/audit-logs" className={pathname === "/audit-logs" ? "navLink active" : "navLink"}>Audit Logs</Link>}
        </nav>
        <div className="userPanel">
          <div className="userName">{user.full_name}</div>
          <div className="userRole">{ROLE_LABELS[user.role]}</div>
          <button className="logoutButton" type="button" onClick={logout}>Logout</button>
        </div>
      </aside>
      <main className="content">
        <div className="appTopBar">
          <div className="notificationBellWrap">
            <button className="notificationBell" type="button" aria-label={`${unreadCount} unread notifications`} onClick={() => { setNotificationsOpen((value) => !value); void loadNotifications(); }}>
              <span aria-hidden="true">🔔</span>{unreadCount > 0 && <span className="notificationCount">{unreadCount > 99 ? "99+" : unreadCount}</span>}
            </button>
            {notificationsOpen && <div className="notificationPopover">
              <div className="recordTitle"><strong>Recent notifications</strong><Link className="link" href="/notifications" onClick={() => setNotificationsOpen(false)}>View all</Link></div>
              {recentNotifications.length === 0 ? <p className="muted">No notifications.</p> : recentNotifications.map((notification) => <Link key={notification.id} href="/notifications" className="notificationPreview" onClick={() => setNotificationsOpen(false)}>
                <strong>{notification.title}</strong><span className="muted">{notification.priority} · {new Date(notification.created_at).toLocaleString()}</span>
              </Link>)}
            </div>}
          </div>
        </div>
        {children}
      </main>
    </div>
  );
}
