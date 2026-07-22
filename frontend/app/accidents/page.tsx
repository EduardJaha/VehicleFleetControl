"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { CreateEntityDialog } from "@/components/ui/CreateEntityDialog";
import { EntityPageHeader } from "@/components/ui/EntityPageHeader";
import { apiDownloadFile, apiGet, apiPostForm } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { toApiDate, todayInputDate } from "@/lib/format";
import type { Accident, ApiMessage } from "@/lib/types";
import { useLanguage } from "@/components/i18n/LanguageProvider";

const initialForm = {
  license_plate: "",
  accident_date: todayInputDate(),
  location: "",
  description: ""
};

export default function AccidentsPage() {
  const { formatDate } = useLanguage();
  const { t } = useTranslation(["modules", "common"]);
  const { can } = useAuth();
  const canWrite = can("accidentsWrite");
  const [accidents, setAccidents] = useState<Accident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [form, setForm] = useState(initialForm);
  const [files, setFiles] = useState<FileList | null>(null);
  const [isAccidentDialogOpen, setIsAccidentDialogOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [filters, setFilters] = useState({ search: "", location: "", from_date: "", to_date: "" });

  async function loadAccidents() {
    setLoading(true);
    setError(null);
    try {
      setAccidents(await apiGet<Accident[]>("/accidents/all"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:accidents.loadError"));
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
    setSubmitting(true);
    try {
      const data = new FormData();
      data.append("license_plate", form.license_plate);
      data.append("accident_date", toApiDate(form.accident_date));
      data.append("location", form.location);
      if (form.description) data.append("description", form.description);
      Array.from(files ?? []).forEach((file) => data.append("files", file));
      const result = await apiPostForm<ApiMessage>("/accidents/report", data);
      setMessage(t("modules:accidents.reported"));
      setForm({ ...initialForm });
      setFiles(null);
      setIsAccidentDialogOpen(false);
      await loadAccidents();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:accidents.reportError"));
    } finally {
      setSubmitting(false);
    }
  }

  function openAccidentDialog() {
    setForm({ ...initialForm });
    setFiles(null);
    setError(null);
    setMessage(null);
    setIsAccidentDialogOpen(true);
  }

  function closeAccidentDialog() {
    if (submitting) return;
    setForm({ ...initialForm });
    setFiles(null);
    setError(null);
    setIsAccidentDialogOpen(false);
  }

  return (
    <section>
      <EntityPageHeader
        title={t("modules:accidents.title")}
        description={t("modules:accidents.description")}
        actionLabel={canWrite ? t("modules:accidents.report") : undefined}
        onAction={canWrite ? openAccidentDialog : undefined}
      />
      {error && !isAccidentDialogOpen && <div className="error spaced" role="alert">{error}</div>}
      {message && <div className="success spaced" role="status">{message}</div>}

      {canWrite && <CreateEntityDialog
        open={isAccidentDialogOpen}
        title={t("modules:accidents.report")}
        description={t("modules:accidents.formDescription")}
        busy={submitting}
        onClose={closeAccidentDialog}
      >
        <form onSubmit={reportAccident} className="form dialogForm">
          {error && <div className="error" role="alert">{error}</div>}
          <div className="formGrid">
            <div className="formRow"><label htmlFor="accident-license-plate">{t("common:labels.licencePlate")}</label><input id="accident-license-plate" className="input" value={form.license_plate} onChange={(e) => setForm({ ...form, license_plate: e.target.value })} placeholder={t("modules:drivers.platePlaceholder")} required /></div>
            <div className="formRow"><label htmlFor="accident-date">{t("modules:accidents.accidentDate")}</label><input id="accident-date" className="input" type="date" value={form.accident_date} onChange={(e) => setForm({ ...form, accident_date: e.target.value })} required /></div>
            <div className="formRow"><label htmlFor="accident-location">{t("common:labels.location")}</label><input id="accident-location" className="input" value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} required /></div>
            <div className="formRow"><label htmlFor="accident-files">{t("modules:accidents.photos")}</label><input id="accident-files" className="input" type="file" accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp" multiple onChange={(e) => setFiles(e.target.files)} /><span className="muted">{t("modules:accidents.photoHelp")}</span></div>
            <div className="formRow span2"><label htmlFor="accident-description">{t("common:labels.description")}</label><textarea id="accident-description" className="input textarea" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></div>
          </div>
          <div className="actions dialogActions">
            <button className="secondaryButton" type="button" onClick={closeAccidentDialog} disabled={submitting}>{t("common:actions.cancel")}</button>
            <button className="button" type="submit" disabled={submitting}>{submitting ? t("modules:accidents.reporting") : t("modules:accidents.report")}</button>
          </div>
        </form>
      </CreateEntityDialog>}

      <div className="card filtersGrid spaced">
        <input className="input" value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} placeholder={t("modules:accidents.searchPlaceholder")} />
        <select className="select" value={filters.location} onChange={(e) => setFilters({ ...filters, location: e.target.value })}><option value="">{t("modules:accidents.allLocations")}</option>{locations.map((location) => <option key={location}>{location}</option>)}</select>
        <input className="input" type="date" value={filters.from_date} onChange={(e) => setFilters({ ...filters, from_date: e.target.value })} />
        <input className="input" type="date" value={filters.to_date} onChange={(e) => setFilters({ ...filters, to_date: e.target.value })} />
      </div>

      {loading ? <div className="card">{t("modules:accidents.loading")}</div> : (
        <table className="table">
          <thead><tr><th>{t("common:labels.licencePlate")}</th><th>{t("common:labels.vehicle")}</th><th>{t("common:labels.date")}</th><th>{t("common:labels.location")}</th><th>{t("common:labels.description")}</th><th>{t("modules:accidents.files")}</th></tr></thead>
          <tbody>
            {filtered.map((a) => <tr key={a.id}><td><strong>{a.license_plate ?? "-"}</strong></td><td>{a.brand ?? ""} {a.model ?? ""}</td><td>{formatDate(a.accident_date)}</td><td>{a.location ?? "-"}</td><td>{a.description ?? "-"}</td><td>{a.files.length > 0 ? a.files.map((file, index) => <button key={file} className="linkButton stackedLink" type="button" onClick={() => void apiDownloadFile(file, `accident-${a.id}-${index + 1}`)}>{t("modules:accidents.downloadNumber", { number: index + 1 })}</button>) : "-"}</td></tr>)}
            {filtered.length === 0 && <tr><td colSpan={6} className="muted">{t("modules:accidents.empty")}</td></tr>}
          </tbody>
        </table>
      )}
    </section>
  );
}
