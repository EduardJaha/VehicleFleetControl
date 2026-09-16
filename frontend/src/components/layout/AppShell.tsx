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
  { href: "/dashboard", labelKey: "dashboard", permission: "dashboard.view" },
  { href: "/vehicles", labelKey: "vehicles", permission: "vehicles.view" },
  { href: "/drivers", labelKey: "drivers", permission: "drivers.view" },
  { href: "/vehicle-assignments", labelKey: "vehicleAssignments", permission: "assignments.view" },
  { href: "/reports", labelKey: "reports", permission: "reports.view" },
  { href: "/compliance/documents", labelKey: "documentCompliance", permission: "documents.view" },
  { href: "/fuel", labelKey: "fuel", permission: "fuel.view" },
  { href: "/accidents", labelKey: "accidents", permission: "accidents.view" },
  { href: "/reservations", labelKey: "reservations", permission: "reservations.view" }
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
  const { user, ready, logout, can, switchCompany } = useAuth();
  const { t } = useTranslation(["common", "navigation", "modules"]);
  const { formatDateTime } = useLanguage();
  const isLoginPage = pathname === "/login";
  const maintenanceActive = pathname.startsWith("/maintenance") || pathname.startsWith("/work-orders") || pathname.startsWith("/services") || pathname.startsWith("/inspections") || pathname.startsWith("/admin/inspection-templates");
  const administrationActive = pathname === "/audit-logs" || pathname.startsWith("/admin/users") || pathname.startsWith("/admin/roles");
  const administrationVisible = can("audit_logs.view") || can("users.manage") || can("roles.manage");
  const [unreadCount, setUnreadCount] = useState(0);
  const [recentNotifications, setRecentNotifications] = useState<Notification[]>([]);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [sessionError, setSessionError] = useState("");

  const loadNotifications = useCallback(async () => {
    if (!user || user.password_reset_required) return;
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
    } else if (ready && user?.password_reset_required && pathname !== "/account/password") {
      router.replace("/account/password");
    }
  }, [isLoginPage, pathname, ready, router, user]);

  useEffect(() => {
    if (!user || user.password_reset_required) return;
    void loadNotifications();
    const timer = window.setInterval(() => void loadNotifications(), 60_000);
    return () => window.clearInterval(timer);
  }, [loadNotifications, pathname, user]);

  useEffect(() => setMobileNavOpen(false), [pathname]);
  useEffect(() => { setUnreadCount(0); setRecentNotifications([]); setNotificationsOpen(false); }, [user?.id, user?.company_id]);

  if (isLoginPage) {
    return <>{children}</>;
  }

  if (!ready || !user || (user.password_reset_required && pathname !== "/account/password")) {
    return (
      <div className="authLoading">
        <div className="card">{t("common:states.loadingSession")}</div>
      </div>
    );
  }

  return (
    <div className="shell">
      <aside className={mobileNavOpen ? "sidebar mobileOpen" : "sidebar"}>
        <div className="sidebarHeader">
          <div className="brand">{t("common:appName")}</div>
          <button className="mobileNavButton" type="button" aria-expanded={mobileNavOpen} aria-controls="primary-navigation" aria-label={t(mobileNavOpen ? "modules:shell.closeNavigation" : "modules:shell.openNavigation")} onClick={() => setMobileNavOpen((value) => !value)}>
            <span aria-hidden="true">{mobileNavOpen ? "×" : "☰"}</span>
          </button>
        </div>
        <nav id="primary-navigation">
          {navItems.slice(0, 3).filter((item) => can(item.permission)).map((item) => <Link key={item.href} href={item.href} className={pathname === item.href ? "navLink active" : "navLink"}>{t(`navigation:${item.labelKey}`)}</Link>)}
          {MAINTENANCE_LINKS.some(item => can(item.permission)) && <details className="navGroup" open={maintenanceActive}>
            <summary className={maintenanceActive ? "navLink active" : "navLink"}>{t("navigation:maintenance")}</summary>
            <div className="navSubmenu">
              {MAINTENANCE_LINKS.filter((item) => can(item.permission)).map((item) => (
                <Link key={item.href} href={item.href} className={pathname === item.href || (item.href !== "/maintenance" && pathname.startsWith(`${item.href}/`)) ? "navLink navSubLink active" : "navLink navSubLink"}>{t(`navigation:${item.labelKey}`)}</Link>
              ))}
            </div>
          </details>}
          {navItems.slice(3).filter((item) => can(item.permission)).map((item) => <Link key={item.href} href={item.href} className={pathname === item.href ? "navLink active" : "navLink"}>{t(`navigation:${item.labelKey}`)}</Link>)}
          {can("imports.manage") && <Link href="/imports" className={pathname === "/imports" ? "navLink active" : "navLink"}>{t("navigation:imports")}</Link>}
          <Link href="/notifications" className={pathname === "/notifications" ? "navLink active" : "navLink"}>{t("navigation:notifications")}</Link>
          {administrationVisible && <details className="navGroup" open={administrationActive}>
            <summary className={administrationActive ? "navLink active" : "navLink"}>{t("navigation:administrationSecurity")}</summary>
            <div className="navSubmenu">
              {can("audit_logs.view") && <Link href="/audit-logs" className={pathname === "/audit-logs" ? "navLink navSubLink active" : "navLink navSubLink"}>{t("navigation:auditLogs")}</Link>}
              {can("users.manage") && <Link href="/admin/users" className={pathname.startsWith("/admin/users") ? "navLink navSubLink active" : "navLink navSubLink"}>{t("navigation:users")}</Link>}
              {can("roles.manage") && <Link href="/admin/roles" className={pathname.startsWith("/admin/roles") ? "navLink navSubLink active" : "navLink navSubLink"}>{t("navigation:rolesPermissions")}</Link>}
            </div>
          </details>}
          {can("settings.manage") && <Link href="/admin/settings" className={pathname.startsWith("/admin/settings") ? "navLink active" : "navLink"}>{t("navigation:organizationSettings")}</Link>}
        </nav>
        <div className="userPanel">
          {user.companies?.length > 1 && <label className="companySwitcher">
            <span>{t("modules:admin.company")}</span>
            <select value={user.company_id} onChange={async (event) => {
              try { await switchCompany(Number(event.target.value)); }
              catch (error) { setSessionError(error instanceof Error ? error.message : t("modules:admin.requestFailed")); }
            }}>
              {user.companies.map((company) => <option key={company.id} value={company.id}>{company.name}</option>)}
            </select>
          </label>}
          <div className="userName">{user.full_name}</div>
          <div className="userRole">{t(`common:roles.${user.role}`, { defaultValue: user.role.replaceAll("_", " ") })}</div>
          <Link href="/account/notifications" className={pathname === "/account/notifications" ? "navLink active" : "navLink"}>{t("navigation:notificationPreferences")}</Link>
          <button className="logoutButton" type="button" onClick={() => { void logout().catch((error) => setSessionError(error instanceof Error ? error.message : t("modules:admin.requestFailed"))); }}>{t("common:actions.logout")}</button>
        </div>
      </aside>
      <main className="content">
        {sessionError && <div className="error" role="alert">{sessionError}</div>}
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
        {user.password_reset_required && <div className="warningBanner">{t("modules:admin.passwordChangeRequired")} <Link className="link" href="/account/password">{t("modules:admin.changePassword")}</Link></div>}
        {children}
      </main>
    </div>
  );
}
