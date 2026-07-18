"use client";

import { useEffect, useMemo, useState } from "react";
import { CreateEntityDialog } from "@/components/ui/CreateEntityDialog";
import { EntityPageHeader } from "@/components/ui/EntityPageHeader";
import { apiDelete, apiDownloadFile, apiGet, apiPostForm } from "@/lib/api";
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
  const [isDocumentDialogOpen, setIsDocumentDialogOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
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
    setSubmitting(true);
    try {
      const data = new FormData();
      data.append("license_plate", form.license_plate);
      data.append("document_type", form.document_type);
      data.append("issue_date", toApiDate(form.issue_date));
      data.append("expiry_date", toApiDate(form.expiry_date));
      data.append("file", file);
      const result = await apiPostForm<ApiMessage>("/papers/upload", data);
      setMessage(result.message ?? "Document uploaded.");
      setForm({ ...initialForm });
      setFile(null);
      setIsDocumentDialogOpen(false);
      await loadPapers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to upload paper");
    } finally {
      setSubmitting(false);
    }
  }

  function openDocumentDialog() {
    setForm({ ...initialForm });
    setFile(null);
    setError(null);
    setMessage(null);
    setIsDocumentDialogOpen(true);
  }

  function closeDocumentDialog() {
    if (submitting) return;
    setForm({ ...initialForm });
    setFile(null);
    setError(null);
    setIsDocumentDialogOpen(false);
  }

  async function deletePaper(paper: VehiclePaper) {
    if (!confirm(`Archive ${paper.document_type} for ${paper.license_plate}?\n\nIt will be hidden from normal views but retained for history and audit purposes.`)) return;
    setError(null);
    setMessage(null);
    try {
      const result = await apiDelete<ApiMessage>(`/papers/${paper.id}`);
      setMessage(result.message ?? "Document archived.");
      await loadPapers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to archive document");
    }
  }

  return (
    <section>
      <EntityPageHeader
        title="Documents"
        description="Manage vehicle papers, expiry dates, and uploaded document files."
        actionLabel={canWrite ? "Add Document" : undefined}
        onAction={canWrite ? openDocumentDialog : undefined}
      />
      {error && !isDocumentDialogOpen && <div className="error spaced" role="alert">{error}</div>}
      {message && <div className="success spaced" role="status">{message}</div>}

      {canWrite && <CreateEntityDialog
        open={isDocumentDialogOpen}
        title="Add Document"
        description="Upload a vehicle document and record its issue and expiry dates."
        busy={submitting}
        onClose={closeDocumentDialog}
      >
        <form onSubmit={uploadPaper} className="form dialogForm">
          {error && <div className="error" role="alert">{error}</div>}
          <div className="formGrid">
            <div className="formRow"><label htmlFor="document-license-plate">License plate</label><input id="document-license-plate" className="input" value={form.license_plate} onChange={(e) => setForm({ ...form, license_plate: e.target.value })} placeholder="01-123-AB" required /></div>
            <div className="formRow"><label htmlFor="document-type">Document type</label><select id="document-type" className="select" value={form.document_type} onChange={(e) => setForm({ ...form, document_type: e.target.value })}>{DOCUMENT_TYPES.map((type) => <option key={type}>{type}</option>)}</select></div>
            <div className="formRow"><label htmlFor="document-issue-date">Issue date</label><input id="document-issue-date" className="input" type="date" value={form.issue_date} onChange={(e) => setForm({ ...form, issue_date: e.target.value })} required /></div>
            <div className="formRow"><label htmlFor="document-expiry-date">Expiry date</label><input id="document-expiry-date" className="input" type="date" min={form.issue_date} value={form.expiry_date} onChange={(e) => setForm({ ...form, expiry_date: e.target.value })} required /></div>
            <div className="formRow span2"><label htmlFor="document-file">Document file</label><input id="document-file" className="input" type="file" accept=".pdf,application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required /><span className="muted">PDF only, maximum 10 MB. Selected: {file?.name ?? "none"}</span></div>
          </div>
          <div className="actions dialogActions">
            <button className="secondaryButton" type="button" onClick={closeDocumentDialog} disabled={submitting}>Cancel</button>
            <button className="button" type="submit" disabled={submitting}>{submitting ? "Uploading..." : "Upload Document"}</button>
          </div>
        </form>
      </CreateEntityDialog>}

      <div className="card filtersGrid spaced">
        <input className="input" value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} placeholder="Search plate, vehicle, document" />
        <select className="select" value={filters.document_type} onChange={(e) => setFilters({ ...filters, document_type: e.target.value })}><option value="">All documents</option>{DOCUMENT_TYPES.map((type) => <option key={type}>{type}</option>)}</select>
        <select className="select" value={filters.location} onChange={(e) => setFilters({ ...filters, location: e.target.value })}><option value="">All locations</option>{locations.map((location) => <option key={location}>{location}</option>)}</select>
        <input className="input" type="date" value={filters.expiring_before} onChange={(e) => setFilters({ ...filters, expiring_before: e.target.value })} title="Expiring before" />
      </div>

      {loading ? <div className="card">Loading documents...</div> : (
        <table className="table">
          <thead><tr><th>Plate</th><th>Vehicle</th><th>Location</th><th>Document</th><th>Issue</th><th>Expiry</th><th>File</th>{canWrite && <th>Actions</th>}</tr></thead>
          <tbody>
            {filtered.map((p) => <tr key={p.id}><td><strong>{p.license_plate}</strong></td><td>{p.brand} {p.model}</td><td>{p.vehicle_location}</td><td>{p.document_type}</td><td>{p.issue_date}</td><td>{p.expiry_date}</td><td>{p.file_path ? <button className="linkButton" type="button" onClick={() => void apiDownloadFile(p.file_path, `${p.document_type}.pdf`)}>Download</button> : "-"}</td>{canWrite && <td><button className="dangerButton smallButton" type="button" onClick={() => void deletePaper(p)}>Archive</button></td>}</tr>)}
            {filtered.length === 0 && <tr><td colSpan={canWrite ? 8 : 7} className="muted">No documents match your filters.</td></tr>}
          </tbody>
        </table>
      )}
    </section>
  );
}
