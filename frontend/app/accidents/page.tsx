"use client";

import { useEffect, useMemo, useState } from "react";
import { apiGet, apiPostForm, fileHref } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { toApiDate, todayInputDate } from "@/lib/format";
import type { Accident, ApiMessage } from "@/lib/types";

const initialForm = {
  license_plate: "",
  accident_date: todayInputDate(),
  location: "",
  description: ""
};

export default function AccidentsPage() {
  const { can } = useAuth();
  const canWrite = can("accidentsWrite");
  const [accidents, setAccidents] = useState<Accident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [form, setForm] = useState(initialForm);
  const [files, setFiles] = useState<FileList | null>(null);
  const [filters, setFilters] = useState({ search: "", location: "", from_date: "", to_date: "" });

  async function loadAccidents() {
    setLoading(true);
    setError(null);
    try {
      setAccidents(await apiGet<Accident[]>("/accidents/all"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load accidents");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadAccidents();
  }, []);

  const locations = useMemo(() => Array.from(new Set(accidents.map((a) => a.location).filter(Boolean) as string[])).sort(), [accidents]);

  const filtered = useMemo(() => {
    const text = filters.search.trim().toLowerCase();
    const from = filters.from_date ? new Date(filters.from_date) : null;
    const to = filters.to_date ? new Date(filters.to_date) : null;
    return accidents.filter((accident) => {
      const [day, month, year] = accident.accident_date.split("-");
      const accidentDate = year ? new Date(`${year}-${month}-${day}`) : null;
      const matchesText = !text || [accident.license_plate ?? "", accident.brand ?? "", accident.model ?? "", accident.description ?? "", accident.location ?? ""].some((value) => value.toLowerCase().includes(text));
      const matchesLocation = !filters.location || accident.location === filters.location;
      const matchesFrom = !from || (accidentDate && accidentDate >= from);
      const matchesTo = !to || (accidentDate && accidentDate <= to);
      return matchesText && matchesLocation && matchesFrom && matchesTo;
    });
  }, [accidents, filters]);

  async function reportAccident(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    try {
      const data = new FormData();
      data.append("license_plate", form.license_plate);
      data.append("accident_date", toApiDate(form.accident_date));
      data.append("location", form.location);
      if (form.description) data.append("description", form.description);
      Array.from(files ?? []).forEach((file) => data.append("files", file));
      const result = await apiPostForm<ApiMessage>("/accidents/report", data);
      setMessage(result.message ?? "Accident reported.");
      setForm(initialForm);
      setFiles(null);
      await loadAccidents();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to report accident");
    }
  }

  return (
    <section>
      <div className="header"><div><h1>Accidents</h1><p className="muted">Report accidents, attach photos/files, and filter accident history.</p></div></div>
      {error && <div className="error spaced">{error}</div>}
      {message && <div className="success spaced">{message}</div>}

      {canWrite && (
        <form onSubmit={reportAccident} className="form card fullWidthForm spaced">
          <h2>Report accident</h2>
          <div className="formGrid">
            <div className="formRow"><label>License plate</label><input className="input" value={form.license_plate} onChange={(e) => setForm({ ...form, license_plate: e.target.value })} placeholder="01-123-AB" required /></div>
            <div className="formRow"><label>Accident date</label><input className="input" type="date" value={form.accident_date} onChange={(e) => setForm({ ...form, accident_date: e.target.value })} required /></div>
            <div className="formRow"><label>Location</label><input className="input" value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} required /></div>
            <div className="formRow"><label>Files/photos</label><input className="input" type="file" multiple onChange={(e) => setFiles(e.target.files)} /></div>
            <div className="formRow span2"><label>Description</label><textarea className="input textarea" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></div>
          </div>
          <button className="button" type="submit">Save accident report</button>
        </form>
      )}

      <div className="card filtersGrid spaced">
        <input className="input" value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} placeholder="Search plate, vehicle, description" />
        <select className="select" value={filters.location} onChange={(e) => setFilters({ ...filters, location: e.target.value })}><option value="">All locations</option>{locations.map((location) => <option key={location}>{location}</option>)}</select>
        <input className="input" type="date" value={filters.from_date} onChange={(e) => setFilters({ ...filters, from_date: e.target.value })} />
        <input className="input" type="date" value={filters.to_date} onChange={(e) => setFilters({ ...filters, to_date: e.target.value })} />
      </div>

      {loading ? <div className="card">Loading accidents...</div> : (
        <table className="table">
          <thead><tr><th>Plate</th><th>Vehicle</th><th>Date</th><th>Location</th><th>Description</th><th>Files</th></tr></thead>
          <tbody>
            {filtered.map((a) => <tr key={a.id}><td><strong>{a.license_plate ?? "-"}</strong></td><td>{a.brand ?? ""} {a.model ?? ""}</td><td>{a.accident_date}</td><td>{a.location ?? "-"}</td><td>{a.description ?? "-"}</td><td>{a.files.length > 0 ? a.files.map((file, index) => <a key={file} className="link stackedLink" href={fileHref(file)} target="_blank">File {index + 1}</a>) : "-"}</td></tr>)}
            {filtered.length === 0 && <tr><td colSpan={6} className="muted">No accident records match your filters.</td></tr>}
          </tbody>
        </table>
      )}
    </section>
  );
}
