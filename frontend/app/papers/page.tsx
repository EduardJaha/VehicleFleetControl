"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { CreateEntityDialog } from "@/components/ui/CreateEntityDialog";
import { EntityPageHeader } from "@/components/ui/EntityPageHeader";
import { apiDelete, apiDownloadFile, apiGet, apiPostForm } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { DOCUMENT_TYPES } from "@/lib/constants";
import { toApiDate, todayInputDate } from "@/lib/format";
import type { ApiMessage, VehiclePaper } from "@/lib/types";
import { translateType } from "@/i18n/translate";
import { useLanguage } from "@/components/i18n/LanguageProvider";

const initialForm = {
  license_plate: "",
  document_type: "Registration",
  issue_date: todayInputDate(),
  expiry_date: ""
};

export default function PapersPage() {
  const { formatDate } = useLanguage();
  const { t } = useTranslation(["modules", "common"]);
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
      setError(err instanceof Error ? err.message : t("modules:documents.loadError"));
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
      setError(t("modules:documents.chooseFile"));
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
      setMessage(t("modules:documents.uploaded"));
      setForm({ ...initialForm });
      setFile(null);
      setIsDocumentDialogOpen(false);
      await loadPapers();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:documents.uploadError"));
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
    if (!confirm(t("modules:documents.archiveConfirm", { type: translateType(paper.document_type), plate: paper.license_plate }))) return;
    setError(null);
    setMessage(null);
    try {
      const result = await apiDelete<ApiMessage>(`/papers/${paper.id}`);
      setMessage(t("modules:documents.archived"));
      await loadPapers();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:documents.archiveError"));
    }
  }

  return (
    <section>
      <EntityPageHeader
        title={t("modules:documents.title")}
        description={t("modules:documents.description")}
        actionLabel={canWrite ? t("modules:documents.add") : undefined}
        onAction={canWrite ? openDocumentDialog : undefined}
      />
      {error && !isDocumentDialogOpen && <div className="error spaced" role="alert">{error}</div>}
      {message && <div className="success spaced" role="status">{message}</div>}

      {canWrite && <CreateEntityDialog
        open={isDocumentDialogOpen}
        title={t("modules:documents.add")}
        description={t("modules:documents.formDescription")}
        busy={submitting}
        onClose={closeDocumentDialog}
      >
        <form onSubmit={uploadPaper} className="form dialogForm">
          {error && <div className="error" role="alert">{error}</div>}
          <div className="formGrid">
            <div className="formRow"><label htmlFor="document-license-plate">{t("common:labels.licencePlate")}</label><input id="document-license-plate" className="input" value={form.license_plate} onChange={(e) => setForm({ ...form, license_plate: e.target.value })} placeholder={t("modules:drivers.platePlaceholder")} required /></div>
            <div className="formRow"><label htmlFor="document-type">{t("modules:documents.documentType")}</label><select id="document-type" className="select" value={form.document_type} onChange={(e) => setForm({ ...form, document_type: e.target.value })}>{DOCUMENT_TYPES.map((type) => <option key={type} value={type}>{translateType(type)}</option>)}</select></div>
            <div className="formRow"><label htmlFor="document-issue-date">{t("common:labels.issueDate")}</label><input id="document-issue-date" className="input" type="date" value={form.issue_date} onChange={(e) => setForm({ ...form, issue_date: e.target.value })} required /></div>
            <div className="formRow"><label htmlFor="document-expiry-date">{t("common:labels.expiryDate")}</label><input id="document-expiry-date" className="input" type="date" min={form.issue_date} value={form.expiry_date} onChange={(e) => setForm({ ...form, expiry_date: e.target.value })} required /></div>
            <div className="formRow span2"><label htmlFor="document-file">{t("modules:documents.documentFile")}</label><input id="document-file" className="input" type="file" accept=".pdf,application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required /><span className="muted">{t("modules:documents.fileHelp", { name: file?.name ?? t("common:labels.none") })}</span></div>
          </div>
          <div className="actions dialogActions">
            <button className="secondaryButton" type="button" onClick={closeDocumentDialog} disabled={submitting}>{t("common:actions.cancel")}</button>
            <button className="button" type="submit" disabled={submitting}>{submitting ? t("modules:documents.uploading") : t("modules:documents.upload")}</button>
          </div>
        </form>
      </CreateEntityDialog>}

      <div className="card filtersGrid spaced">
        <input className="input" value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} placeholder={t("modules:documents.searchPlaceholder")} />
        <select className="select" value={filters.document_type} onChange={(e) => setFilters({ ...filters, document_type: e.target.value })}><option value="">{t("modules:documents.allDocuments")}</option>{DOCUMENT_TYPES.map((type) => <option key={type} value={type}>{translateType(type)}</option>)}</select>
        <select className="select" value={filters.location} onChange={(e) => setFilters({ ...filters, location: e.target.value })}><option value="">{t("modules:documents.allLocations")}</option>{locations.map((location) => <option key={location}>{location}</option>)}</select>
        <input className="input" type="date" value={filters.expiring_before} onChange={(e) => setFilters({ ...filters, expiring_before: e.target.value })} title={t("modules:documents.expiringBefore")} />
      </div>

      {loading ? <div className="card">{t("modules:documents.loading")}</div> : (
        <table className="table">
          <thead><tr><th>{t("common:labels.licencePlate")}</th><th>{t("common:labels.vehicle")}</th><th>{t("common:labels.location")}</th><th>{t("modules:documents.document")}</th><th>{t("modules:documents.issue")}</th><th>{t("modules:documents.expiry")}</th><th>{t("common:labels.file")}</th>{canWrite && <th>{t("common:labels.actions")}</th>}</tr></thead>
          <tbody>
            {filtered.map((p) => <tr key={p.id}><td><strong>{p.license_plate}</strong></td><td>{p.brand} {p.model}</td><td>{p.vehicle_location}</td><td>{translateType(p.document_type)}</td><td>{formatDate(p.issue_date)}</td><td>{formatDate(p.expiry_date)}</td><td>{p.file_path ? <button className="linkButton" type="button" onClick={() => void apiDownloadFile(p.file_path, `${p.document_type}.pdf`)}>{t("common:actions.download")}</button> : "-"}</td>{canWrite && <td><button className="dangerButton smallButton" type="button" onClick={() => void deletePaper(p)}>{t("common:actions.archive")}</button></td>}</tr>)}
            {filtered.length === 0 && <tr><td colSpan={canWrite ? 8 : 7} className="muted">{t("modules:documents.empty")}</td></tr>}
          </tbody>
        </table>
      )}
    </section>
  );
}
