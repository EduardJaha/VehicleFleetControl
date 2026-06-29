import { apiGet } from "@/lib/api";
import type { DashboardSummary } from "@/lib/types";
import { VEHICLE_STATUS_LABELS } from "@/lib/constants";

export default async function DashboardPage() {
  const summary = await apiGet<DashboardSummary>("/dashboard/summary").catch(() => null);

  return (
    <section>
      <div className="header">
        <div>
          <h1>Dashboard</h1>
          <p className="muted">Fleet overview from the FastAPI backend.</p>
        </div>
      </div>

      {!summary ? (
        <div className="error">Could not load dashboard. Make sure the backend is running on port 8000.</div>
      ) : (
        <div className="grid cols-3">
          <div className="card">
            <div className="muted">Total vehicles</div>
            <h2>{summary.total_vehicles}</h2>
          </div>
          <div className="card">
            <div className="muted">By status</div>
            {summary.status_summary.map((item) => (
              <p key={item.status}>{VEHICLE_STATUS_LABELS[item.status] ?? item.status}: <strong>{item.count}</strong></p>
            ))}
          </div>
          <div className="card">
            <div className="muted">By location</div>
            {summary.location_summary.map((item) => (
              <p key={item.location}>{item.location}: <strong>{item.count}</strong></p>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
