import Link from "next/link";

const navItems = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/vehicles", label: "Vehicles" },
  { href: "/papers", label: "Documents" },
  { href: "/services/overview", label: "Services" },
  { href: "/services/reminders", label: "Reminders" },
  { href: "/fuel", label: "Fuel" },
  { href: "/accidents", label: "Accidents" },
  { href: "/reservations", label: "Reservations" }
];

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">Vehicle Fleet Control</div>
        <nav>
          {navItems.map((item) => (
            <Link key={item.href} href={item.href} className="navLink">
              {item.label}
            </Link>
          ))}
        </nav>
      </aside>
      <main className="content">{children}</main>
    </div>
  );
}
