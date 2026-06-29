"use client";

import { useEffect, useMemo, useState } from "react";
import { apiGet } from "@/lib/api";
import { SERVICE_TYPES } from "@/lib/constants";
import type { ServiceReminder } from "@/lib/types";

export default function ServiceRemindersPage() {
  const [reminders, setReminders] = useState<ServiceReminder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState({ search: "", service_type: "", mode: "" });

  async function loadReminders() {
    setLoading(true);
    setError(null);
    try {
      setReminders(await apiGet<ServiceReminder[]>("/services/reminders"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load service reminders");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadReminders();
  }, []);

  const filtered = useMemo(() => {
    const text = filters.search.trim().toLowerCase();
    return reminders.filter((reminder) => {
      const matchesText = !text || [reminder.license_plate, reminder.service_type].some((value) => value.toLowerCase().includes(text));
      const matchesType = !filters.service_type || reminder.service_type === filters.service_type;
      const matchesMode = !filters.mode || reminder.reminder_mode === filters.mode;
      return matchesText && matchesType && matchesMode;
    });
  }, [reminders, filters]);

  return (
    <section>
      <div className="header"><div><h1>Service reminders</h1><p className="muted">Kilometer and date reminders with quick filtering.</p></div><button className="secondaryButton" type="button" onClick={() => void loadReminders()}>Refresh</button></div>
      {error && <div className="error spaced">{error}</div>}
      <div className="card filtersGrid spaced">
        <input className="input" value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} placeholder="Search plate or service" />
        <select className="select" value={filters.service_type} onChange={(e) => setFilters({ ...filters, service_type: e.target.value })}><option value="">All service types</option>{SERVICE_TYPES.map((type) => <option key={type}>{type}</option>)}</select>
        <select className="select" value={filters.mode} onChange={(e) => setFilters({ ...filters, mode: e.target.value })}><option value="">All modes</option><option value="Kilometers">Kilometers</option><option value="Date">Date</option></select>
      </div>
      {loading ? <div className="card">Loading reminders...</div> : (
        <table className="table">
          <thead><tr><th>Plate</th><th>Service</th><th>Service date</th><th>Mode</th><th>Next date</th><th>Days left</th><th>Current KM</th><th>Next KM</th><th>KM left</th></tr></thead>
          <tbody>
            {filtered.map((r, idx) => <tr key={`${r.license_plate}-${r.service_type}-${idx}`}><td><strong>{r.license_plate}</strong></td><td>{r.service_type}</td><td>{r.service_date}</td><td>{r.reminder_mode}</td><td>{r.next_service_date ?? "-"}</td><td>{r.days_left ?? "-"}</td><td>{r.current_odometer_km ?? "-"}</td><td>{r.next_service_odometer_km ?? "-"}</td><td>{r.km_left ?? "-"}</td></tr>)}
            {filtered.length === 0 && <tr><td colSpan={9} className="muted">No reminders match your filters.</td></tr>}
          </tbody>
        </table>
      )}
    </section>
  );
}
