"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { AuthProvider, ROLE_LABELS, useAuth } from "@/lib/auth";
import { MAINTENANCE_LINKS } from "@/components/maintenance/Maintenance";

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

  useEffect(() => {
    if (ready && !user && !isLoginPage) {
      router.replace("/login");
    }
  }, [isLoginPage, ready, router, user]);

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
        </nav>
        <div className="userPanel">
          <div className="userName">{user.full_name}</div>
          <div className="userRole">{ROLE_LABELS[user.role]}</div>
          <button className="logoutButton" type="button" onClick={logout}>Logout</button>
        </div>
      </aside>
      <main className="content">{children}</main>
    </div>
  );
}
