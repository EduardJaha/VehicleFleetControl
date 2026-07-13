"use client";

import { useEffect, useMemo, useState } from "react";
import { apiDelete, apiGet, apiPostForm, fileHref } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { DOCUMENT_TYPES } from "@/lib/constants";
import { toApiDate, todayInputDate } from "@/lib/format";
import type { ApiMessage, VehiclePaper } from "@/lib/types";

const initialForm = {
  license_plate: "",
  document_type: "Registration",
  issue_date: todayInputDate(),
  expiry_date: ""
};

export default function PapersPage() {
  const { can } = useAuth();
  const canWrite = can("papersWrite");
  const [papers, setPapers] = useState<VehiclePaper[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [form, setForm] = useState(initialForm);
  const [file, setFile] = useState<File | null>(null);
  const [filters, setFilters] = useState({ search: "", document_type: "", location: "", expiring_before: "" });

  async function loadPapers() {
    setLoading(true);
    setError(null);
    try {
      setPapers(await apiGet<VehiclePaper[]>("/papers/all"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load papers");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadPapers();
  }, []);

  const locations = useMemo(() => Array.from(new Set(papers.map((p) => p.vehicle_location).filter(Boolean))).sort(), [papers]);

  const filtered = useMemo(() => {
    const text = filters.search.trim().toLowerCase();
    const expiringBefore = filters.expiring_before ? new Date(filters.expiring_before) : null;
    return papers.filter((paper) => {
      const [day, month, year] = paper.expiry_date.split("-");
      const expiryDate = year ? new Date(`${year}-${month}-${day}`) : null;
      const matchesText = !text || [paper.license_plate, paper.brand, paper.model, paper.document_type, paper.vehicle_location].some((value) => value.toLowerCase().includes(text));
      const matchesType = !filters.document_type || paper.document_type === filters.document_type;
      const matchesLocation = !filters.location || paper.vehicle_location === filters.location;
      const matchesExpiry = !expiringBefore || (expiryDate && expiryDate <= expiringBefore);
      return matchesText && matchesType && matchesLocation && matchesExpiry;
    });
  }, [papers, filters]);

  async function uploadPaper(event: React.FormEvent) {
    event.preventDefault();
    if (!file) {
      setError("Choose a document file first.");
      return;
    }
    setError(null);
    setMessage(null);
    try {
      const data = new FormData();
      data.append("license_plate", form.license_plate);
      data.append("document_type", form.document_type);
      data.append("issue_date", toApiDate(form.issue_date));
      data.append("expiry_date", toApiDate(form.expiry_date));
      data.append("file", file);
      const result = await apiPostForm<ApiMessage>("/papers/upload", data);
      setMessage(result.message ?? "Paper uploaded.");
      setForm(initialForm);
      setFile(null);
      await loadPapers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to upload paper");
    }
  }

  async function deletePaper(paper: VehiclePaper) {
    if (!confirm(`Delete ${paper.document_type} for ${paper.license_plate}?`)) return;
    setError(null);
    setMessage(null);
    try {
      const result = await apiDelete<ApiMessage>(`/papers/${paper.id}`);
      setMessage(result.message ?? "Paper deleted.");
      await loadPapers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete paper");
    }
  }

  return (
    <section>
      <div className="header"><div><h1>Papers</h1><p className="muted">Upload vehicle documents, filter papers, open files, and delete old documents.</p></div></div>
      {error && <div className="error spaced">{error}</div>}
      {message && <div className="success spaced">{message}</div>}

      {canWrite && (
        <form onSubmit={uploadPaper} className="form card fullWidthForm spaced">
          <h2>Upload paper</h2>
          <div className="formGrid">
            <div className="formRow"><label>License plate</label><input className="input" value={form.license_plate} onChange={(e) => setForm({ ...form, license_plate: e.target.value })} placeholder="01-123-AB" required /></div>
            <div className="formRow"><label>Document type</label><select className="select" value={form.document_type} onChange={(e) => setForm({ ...form, document_type: e.target.value })}>{DOCUMENT_TYPES.map((type) => <option key={type}>{type}</option>)}</select></div>
            <div className="formRow"><label>Issue date</label><input className="input" type="date" value={form.issue_date} onChange={(e) => setForm({ ...form, issue_date: e.target.value })} required /></div>
            <div className="formRow"><label>Expiry date</label><input className="input" type="date" value={form.expiry_date} onChange={(e) => setForm({ ...form, expiry_date: e.target.value })} required /></div>
            <div className="formRow span2"><label>Document file</label><input className="input" type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required /></div>
          </div>
          <button className="button" type="submit">Upload paper</button>
        </form>
      )}

      <div className="card filtersGrid spaced">
        <input className="input" value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} placeholder="Search plate, vehicle, document" />
        <select className="select" value={filters.document_type} onChange={(e) => setFilters({ ...filters, document_type: e.target.value })}><option value="">All documents</option>{DOCUMENT_TYPES.map((type) => <option key={type}>{type}</option>)}</select>
        <select className="select" value={filters.location} onChange={(e) => setFilters({ ...filters, location: e.target.value })}><option value="">All locations</option>{locations.map((location) => <option key={location}>{location}</option>)}</select>
        <input className="input" type="date" value={filters.expiring_before} onChange={(e) => setFilters({ ...filters, expiring_before: e.target.value })} title="Expiring before" />
      </div>

      {loading ? <div className="card">Loading papers...</div> : (
        <table className="table">
          <thead><tr><th>Plate</th><th>Vehicle</th><th>Location</th><th>Document</th><th>Issue</th><th>Expiry</th><th>File</th>{canWrite && <th>Actions</th>}</tr></thead>
          <tbody>
            {filtered.map((p) => <tr key={p.id}><td><strong>{p.license_plate}</strong></td><td>{p.brand} {p.model}</td><td>{p.vehicle_location}</td><td>{p.document_type}</td><td>{p.issue_date}</td><td>{p.expiry_date}</td><td>{p.file_path ? <a className="link" href={fileHref(p.file_path)} target="_blank">Open</a> : "-"}</td>{canWrite && <td><button className="dangerButton smallButton" type="button" onClick={() => void deletePaper(p)}>Delete</button></td>}</tr>)}
            {filtered.length === 0 && <tr><td colSpan={canWrite ? 8 : 7} className="muted">No papers match your filters.</td></tr>}
          </tbody>
        </table>
      )}
    </section>
  );
}
