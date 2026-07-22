"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiDownload, apiGet, buildQuery, vehicleRegistrationApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { REPORTS, VEHICLE_STATUSES } from "@/lib/constants";
import { toApiDate } from "@/lib/format";
import type { RegistrationCountryCode, RegistrationCountryOption, ReportData } from "@/lib/types";
import { useLanguage } from "@/components/i18n/LanguageProvider";

type ReportFilters = {
  from_date: string;
  to_date: string;
  license_plate: string;
  registration_country: RegistrationCountryCode | "";
  vehicle_status: string;
  department: string;
  driver_id: string;
};

const initialFilters: ReportFilters = {
  from_date: "",
  to_date: "",
  license_plate: "",
  registration_country: "",
  vehicle_status: "",
  department: "",
  driver_id: ""
};

function humanize(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default function ReportsPage() {
  const { t } = useTranslation(["modules", "common"]);
  const { formatNumber } = useLanguage();
  const formatValue = (value: unknown) => {
    if (value === null || value === undefined || value === "") return "-";
    if (typeof value === "number") return formatNumber(value, Number.isInteger(value) ? {} : { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return String(value);
  };
  const translateHeader = (value: string) => t(`modules:reports.columns.${value}`, { defaultValue: humanize(value) });
  const { can } = useAuth();
  const canReadReports = can("reportsRead");
  const [selectedReport, setSelectedReport] = useState("fleet-summary");
  const [filters, setFilters] = useState<ReportFilters>(initialFilters);
  const [summary, setSummary] = useState<ReportData | null>(null);
  const [report, setReport] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [countries, setCountries] = useState<RegistrationCountryOption[]>([]);

  const query = useMemo(() => buildQuery({
    from_date: toApiDate(filters.from_date),
    to_date: toApiDate(filters.to_date),
    license_plate: filters.license_plate,
    registration_country: filters.registration_country,
    vehicle_status: filters.vehicle_status,
    department: filters.department,
    driver_id: filters.driver_id
  }), [filters]);

  async function loadReports(reportName = selectedReport) {
    if (!canReadReports) return;
    setLoading(true);
    setError(null);
    setMessage(null);
    try {
      const [summaryData, reportData] = await Promise.all([
        apiGet<ReportData>(`/reports/fleet-summary${query}`),
        apiGet<ReportData>(`/reports/${reportName}${query}`)
      ]);
      setSummary(summaryData);
      setReport(reportData);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:reports.loadError"));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadReports(selectedReport);
    void vehicleRegistrationApi.getCountries().then(setCountries).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canReadReports, selectedReport]);

  async function exportReport(reportName: string) {
    setError(null);
    setMessage(null);
    try {
      await apiDownload(`/reports/${reportName}/export${query}`, `${reportName}.xlsx`);
      setMessage(t("modules:reports.exportDownloaded"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:reports.exportError"));
    }
  }

  if (!canReadReports) {
    return <div className="error">{t("modules:reports.accessDenied")}</div>;
  }

  const headers = report?.rows[0] ? Object.keys(report.rows[0]) : [];

  return (
    <section>
      <div className="header">
        <div>
          <h1>{t("modules:reports.title")}</h1>
          <p className="muted">{t("modules:reports.description")}</p>
        </div>
      </div>

      {error && <div className="error spaced">{error}</div>}
      {message && <div className="success spaced">{message}</div>}

      <div className="grid cols-3 spaced">
        {(summary ? Object.entries(summary.kpis).slice(0, 6) : []).map(([key, value]) => (
          <div className="card" key={key}>
            <div className="muted">{translateHeader(key)}</div>
            <h2>{formatValue(value)}</h2>
          </div>
        ))}
      </div>

      <div className="card filtersGrid spaced">
        <select className="select" value={selectedReport} onChange={(event) => setSelectedReport(event.target.value)}>
          {REPORTS.map((reportOption) => <option key={reportOption.value} value={reportOption.value}>{t(`modules:${reportOption.labelKey}`)}</option>)}
        </select>
        <input className="input" type="date" value={filters.from_date} onChange={(event) => setFilters({ ...filters, from_date: event.target.value })} />
        <input className="input" type="date" value={filters.to_date} onChange={(event) => setFilters({ ...filters, to_date: event.target.value })} />
        <input className="input" value={filters.license_plate} onChange={(event) => setFilters({ ...filters, license_plate: event.target.value })} placeholder={t("modules:reports.platePlaceholder")} />
        <select className="select" value={filters.registration_country} onChange={(event) => setFilters({ ...filters, registration_country: event.target.value as RegistrationCountryCode | "" })}>
          <option value="">{t("modules:reports.allCountries")}</option>
          {countries.map((country) => <option key={country.code} value={country.code}>{t(`common:countries.${country.code}`)}</option>)}
        </select>
        <select className="select" value={filters.vehicle_status} onChange={(event) => setFilters({ ...filters, vehicle_status: event.target.value })}>
          <option value="">{t("modules:reports.allVehicleStatuses")}</option>
          {VEHICLE_STATUSES.map((status) => <option key={status.value} value={status.value}>{t(`common:${status.labelKey}`)}</option>)}
        </select>
        <input className="input" value={filters.department} onChange={(event) => setFilters({ ...filters, department: event.target.value })} placeholder={t("common:labels.department")} />
        <input className="input" type="number" value={filters.driver_id} onChange={(event) => setFilters({ ...filters, driver_id: event.target.value })} placeholder={t("modules:reports.driverId")} />
        <button className="button" type="button" onClick={() => void loadReports()}>{t("common:actions.applyFilters")}</button>
      </div>

      <div className="actions spaced">
        {REPORTS.map((reportOption) => (
          <button key={reportOption.value} className={reportOption.value === selectedReport ? "button smallButton" : "secondaryButton smallButton"} type="button" onClick={() => void exportReport(reportOption.value)}>
            {t("common:actions.export")} {t(`modules:${reportOption.labelKey}`)}
          </button>
        ))}
      </div>

      {loading ? <div className="card">{t("modules:reports.loading")}</div> : (
        <div>
          <div className="header">
            <h2>{t(`modules:${REPORTS.find((item) => item.value === selectedReport)?.labelKey ?? "reports.fleet-summary"}`)}</h2>
            <button className="button" type="button" onClick={() => void exportReport(selectedReport)}>{t("modules:reports.exportSelected")}</button>
          </div>
          <div className="grid cols-3 spaced">
            {report && Object.entries(report.kpis).map(([key, value]) => (
              <div className="card" key={key}>
                <div className="muted">{translateHeader(key)}</div>
                <h2>{formatValue(value)}</h2>
              </div>
            ))}
          </div>

          <table className="table">
            <thead><tr>{headers.map((header) => <th key={header}>{translateHeader(header)}</th>)}</tr></thead>
            <tbody>
              {report?.rows.map((row, index) => (
                <tr key={index}>
                  {headers.map((header) => <td key={header}>{formatValue(row[header])}</td>)}
                </tr>
              ))}
              {(!report || report.rows.length === 0) && <tr><td className="muted">{t("modules:reports.empty")}</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
