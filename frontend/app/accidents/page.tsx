"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { CreateEntityDialog } from "@/components/ui/CreateEntityDialog";
import { EntityPageHeader } from "@/components/ui/EntityPageHeader";
import { apiDownloadFile, apiGet, apiPost, apiPostForm } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Accident, ApiMessage, Driver, Vehicle } from "@/lib/types";
import { useLanguage } from "@/components/i18n/LanguageProvider";

function localDateTime() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

const initialForm = {
  vehicle_id: "",
  driver_id: "",
  assignment_id: "",
  reservation_id: "",
  accident_datetime: localDateTime(),
  location: "",
  severity: "Minor",
  police_involved: false,
  police_report_number: "",
  description: "",
  vehicle_available_after_accident: true,
  estimated_damage_cost: "",
  actual_damage_cost: "",
  fault_determination: ""
};

export default function AccidentsPage() {
  const { formatDate } = useLanguage();
  const { t } = useTranslation(["modules", "common"]);
  const { can } = useAuth();
  const canWrite = can("accidentsWrite");
  const [accidents, setAccidents] = useState<Accident[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [drivers, setDrivers] = useState<Driver[]>([]);
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
    if (canWrite) {
      void Promise.all([
        apiGet<Vehicle[]>("/vehicles"),
        apiGet<Driver[]>("/drivers")
      ]).then(([vehicleRows, driverRows]) => {
        setVehicles(vehicleRows);
        setDrivers(driverRows);
      }).catch(() => undefined);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      const result = await apiPost<Accident>("/accidents", {
        vehicle_id: Number(form.vehicle_id),
        driver_id: Number(form.driver_id),
        assignment_id: form.assignment_id ? Number(form.assignment_id) : null,
        reservation_id: form.reservation_id ? Number(form.reservation_id) : null,
        accident_datetime: new Date(form.accident_datetime).toISOString(),
        location: form.location,
        severity: form.severity,
        police_involved: form.police_involved,
        police_report_number: form.police_report_number || null,
        description: form.description || null,
        vehicle_available_after_accident: form.vehicle_available_after_accident,
        estimated_damage_cost: form.estimated_damage_cost || null,
        actual_damage_cost: form.actual_damage_cost || null,
        fault_determination: form.fault_determination || null
      });
      for (const file of Array.from(files ?? [])) {
        const data = new FormData();
        data.append("entity_type", "VehicleAccident");
        data.append("entity_id", String(result.id));
        data.append("category", "auto");
        data.append("file", file);
        await apiPostForm<ApiMessage>("/files", data);
      }
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
            <div className="formRow"><label htmlFor="accident-vehicle">{t("common:labels.vehicle")}</label><select id="accident-vehicle" className="select" value={form.vehicle_id} onChange={(e) => setForm({ ...form, vehicle_id: e.target.value })} required><option value="">{t("modules:accidents.selectVehicle")}</option>{vehicles.map((vehicle) => <option key={vehicle.id} value={vehicle.id}>{vehicle.license_plate} · {vehicle.brand} {vehicle.model}</option>)}</select></div>
            <div className="formRow"><label htmlFor="accident-driver">{t("common:labels.driver")}</label><select id="accident-driver" className="select" value={form.driver_id} onChange={(e) => setForm({ ...form, driver_id: e.target.value })} required><option value="">{t("modules:accidents.selectDriver")}</option>{drivers.map((driver) => <option key={driver.id} value={driver.id}>{driver.full_name} · {driver.employee_number}</option>)}</select></div>
            <div className="formRow"><label htmlFor="accident-assignment">{t("modules:accidents.assignmentId")}</label><input id="accident-assignment" className="input" type="number" min="1" value={form.assignment_id} onChange={(e) => setForm({ ...form, assignment_id: e.target.value })} /></div>
            <div className="formRow"><label htmlFor="accident-reservation">{t("modules:accidents.reservationId")}</label><input id="accident-reservation" className="input" type="number" min="1" value={form.reservation_id} onChange={(e) => setForm({ ...form, reservation_id: e.target.value })} /></div>
            <div className="formRow"><label htmlFor="accident-date">{t("modules:accidents.accidentDate")}</label><input id="accident-date" className="input" type="datetime-local" value={form.accident_datetime} onChange={(e) => setForm({ ...form, accident_datetime: e.target.value })} required /></div>
            <div className="formRow"><label htmlFor="accident-location">{t("common:labels.location")}</label><input id="accident-location" className="input" value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} required /></div>
            <div className="formRow"><label htmlFor="accident-severity">{t("modules:accidents.severity")}</label><select id="accident-severity" className="select" value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })}>{["Minor", "Moderate", "Severe", "Critical"].map((value) => <option key={value}>{value}</option>)}</select></div>
            <div className="formRow"><label className="actions"><input type="checkbox" checked={form.police_involved} onChange={(e) => setForm({ ...form, police_involved: e.target.checked, police_report_number: e.target.checked ? form.police_report_number : "" })} /> {t("modules:accidents.policeInvolved")}</label></div>
            <div className="formRow"><label htmlFor="accident-police-report">{t("modules:accidents.policeReport")}</label><input id="accident-police-report" className="input" disabled={!form.police_involved} value={form.police_report_number} onChange={(e) => setForm({ ...form, police_report_number: e.target.value })} /></div>
            <div className="formRow"><label className="actions"><input type="checkbox" checked={form.vehicle_available_after_accident} onChange={(e) => setForm({ ...form, vehicle_available_after_accident: e.target.checked })} /> {t("modules:accidents.vehicleAvailable")}</label></div>
            <div className="formRow"><label htmlFor="accident-estimate">{t("modules:accidents.estimatedDamage")}</label><input id="accident-estimate" className="input" type="number" min="0" step="0.01" value={form.estimated_damage_cost} onChange={(e) => setForm({ ...form, estimated_damage_cost: e.target.value })} /></div>
            <div className="formRow"><label htmlFor="accident-actual">{t("modules:accidents.actualDamage")}</label><input id="accident-actual" className="input" type="number" min="0" step="0.01" value={form.actual_damage_cost} onChange={(e) => setForm({ ...form, actual_damage_cost: e.target.value })} /></div>
            <div className="formRow"><label htmlFor="accident-fault">{t("modules:accidents.fault")}</label><input id="accident-fault" className="input" value={form.fault_determination} onChange={(e) => setForm({ ...form, fault_determination: e.target.value })} /></div>
            <div className="formRow"><label htmlFor="accident-files">{t("modules:accidents.photos")}</label><input id="accident-files" className="input" type="file" accept=".jpg,.jpeg,.png,.webp,.pdf,image/jpeg,image/png,image/webp,application/pdf" multiple onChange={(e) => setFiles(e.target.files)} /><span className="muted">{t("modules:accidents.photoHelp")}</span></div>
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
            {filtered.map((a) => <tr key={a.id}><td><Link className="link" href={`/accidents/${a.id}`}>{a.license_plate ?? "-"}</Link></td><td>{a.brand ?? ""} {a.model ?? ""}</td><td>{formatDate(a.accident_date)}</td><td>{a.location ?? "-"}</td><td>{a.status ?? "Reported"} · {a.description ?? "-"}</td><td>{a.files.length > 0 ? a.files.map((file, index) => <button key={file} className="linkButton stackedLink" type="button" onClick={() => void apiDownloadFile(file, `accident-${a.id}-${index + 1}`)}>{t("modules:accidents.downloadNumber", { number: index + 1 })}</button>) : "-"}</td></tr>)}
            {filtered.length === 0 && <tr><td colSpan={6} className="muted">{t("modules:accidents.empty")}</td></tr>}
          </tbody>
        </table>
      )}
    </section>
  );
}
