import Link from "next/link";
import type { ReactNode } from "react";

type Props = {
  title: string;
  description?: string;
  href?: string;
  actionLabel?: string;
  className?: string;
  children: ReactNode;
};

export function DashboardCard({ title, description, href, actionLabel, className = "", children }: Props) {
  return (
    <section className={`card dashboardCard ${className}`.trim()}>
      <div className="dashboardCardHeader">
        <div>
          <h2>{title}</h2>
          {description && <p className="muted">{description}</p>}
        </div>
        {href && actionLabel && <Link className="dashboardCardLink" href={href}>{actionLabel} <span aria-hidden="true">→</span></Link>}
      </div>
      {children}
    </section>
  );
}

export function Metric({ label, value, tone }: { label: string; value: ReactNode; tone?: "danger" | "warning" | "success" }) {
  return (
    <div className={`dashboardMetric ${tone ? `dashboardMetric-${tone}` : ""}`.trim()}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
