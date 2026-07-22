"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { AuthProvider, useAuth } from "@/lib/auth";
import { MAINTENANCE_LINKS } from "@/components/maintenance/Maintenance";
import { apiGet } from "@/lib/api";
import type { Notification, PageResult } from "@/lib/types";
import { LanguageSelector } from "@/components/i18n/LanguageSelector";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import { translateNotification, translateStatus } from "@/i18n/translate";

const navItems = [
  { href: "/dashboard", labelKey: "dashboard" },
  { href: "/vehicles", labelKey: "vehicles" },
  { href: "/drivers", labelKey: "drivers" },
  { href: "/reports", labelKey: "reports" },
  { href: "/papers", labelKey: "documents" },
  { href: "/fuel", labelKey: "fuel" },
  { href: "/accidents", labelKey: "accidents" },
  { href: "/reservations", labelKey: "reservations" }
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
  const { t } = useTranslation(["common", "navigation", "modules"]);
  const { formatDateTime } = useLanguage();
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
        <div className="card">{t("common:states.loadingSession")}</div>
      </div>
    );
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">{t("common:appName")}</div>
        <nav>
          {navItems.slice(0, 3).map((item) => <Link key={item.href} href={item.href} className={pathname === item.href ? "navLink active" : "navLink"}>{t(`navigation:${item.labelKey}`)}</Link>)}
          <details className="navGroup" open={maintenanceActive}>
            <summary className={maintenanceActive ? "navLink active" : "navLink"}>{t("navigation:maintenance")}</summary>
            <div className="navSubmenu">
              {MAINTENANCE_LINKS.filter((item) => item.roles.includes(user.role)).map((item) => (
                <Link key={item.href} href={item.href} className={pathname === item.href || (item.href !== "/maintenance" && pathname.startsWith(`${item.href}/`)) ? "navLink navSubLink active" : "navLink navSubLink"}>{t(`navigation:${item.labelKey}`)}</Link>
              ))}
            </div>
          </details>
          {navItems.slice(3).map((item) => <Link key={item.href} href={item.href} className={pathname === item.href ? "navLink active" : "navLink"}>{t(`navigation:${item.labelKey}`)}</Link>)}
          <Link href="/notifications" className={pathname === "/notifications" ? "navLink active" : "navLink"}>{t("navigation:notifications")}</Link>
          {user.role === "admin" && <Link href="/audit-logs" className={pathname === "/audit-logs" ? "navLink active" : "navLink"}>{t("navigation:auditLogs")}</Link>}
        </nav>
        <div className="userPanel">
          <div className="userName">{user.full_name}</div>
          <div className="userRole">{t(`common:roles.${user.role}`)}</div>
          <button className="logoutButton" type="button" onClick={logout}>{t("common:actions.logout")}</button>
        </div>
      </aside>
      <main className="content">
        <div className="appTopBar">
          <LanguageSelector compact />
          <div className="notificationBellWrap">
            <button className="notificationBell" type="button" aria-label={t("modules:shell.unreadNotifications", { count: unreadCount })} onClick={() => { setNotificationsOpen((value) => !value); void loadNotifications(); }}>
              <span aria-hidden="true">🔔</span>{unreadCount > 0 && <span className="notificationCount">{unreadCount > 99 ? "99+" : unreadCount}</span>}
            </button>
            {notificationsOpen && <div className="notificationPopover">
              <div className="recordTitle"><strong>{t("modules:shell.recentNotifications")}</strong><Link className="link" href="/notifications" onClick={() => setNotificationsOpen(false)}>{t("common:actions.viewAll")}</Link></div>
              {recentNotifications.length === 0 ? <p className="muted">{t("modules:shell.noNotifications")}</p> : recentNotifications.map((notification) => <Link key={notification.id} href="/notifications" className="notificationPreview" onClick={() => setNotificationsOpen(false)}>
                <strong>{translateNotification(notification.title_key, notification.message_params, notification.title)}</strong><span className="muted">{translateStatus(notification.priority)} · {formatDateTime(notification.created_at)}</span>
              </Link>)}
            </div>}
          </div>
        </div>
        {children}
      </main>
    </div>
  );
}
