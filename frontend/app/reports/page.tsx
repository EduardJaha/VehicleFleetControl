"use client";

import { useEffect, useMemo, useState } from "react";
import { apiDownload, apiGet, buildQuery } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { REPORTS, VEHICLE_STATUSES } from "@/lib/constants";
import { toApiDate } from "@/lib/format";
import type { ReportData } from "@/lib/types";

type ReportFilters = {
  from_date: string;
  to_date: string;
  license_plate: string;
  vehicle_status: string;
  department: string;
  driver_id: string;
};

const initialFilters: ReportFilters = {
  from_date: "",
  to_date: "",
  license_plate: "",
  vehicle_status: "",
  department: "",
  driver_id: ""
};

function humanize(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return Number.isInteger(value) ? value.toString() : value.toFixed(2);
  return String(value);
}

export default function ReportsPage() {
  const { can } = useAuth();
  const canReadReports = can("reportsRead");
  const [selectedReport, setSelectedReport] = useState("fleet-summary");
  const [filters, setFilters] = useState<ReportFilters>(initialFilters);
  const [summary, setSummary] = useState<ReportData | null>(null);
  const [report, setReport] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const query = useMemo(() => buildQuery({
    from_date: toApiDate(filters.from_date),
    to_date: toApiDate(filters.to_date),
    license_plate: filters.license_plate,
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
      setError(err instanceof Error ? err.message : "Could not load reports");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadReports(selectedReport);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canReadReports, selectedReport]);

  async function exportReport(reportName: string) {
    setError(null);
    setMessage(null);
    try {
      await apiDownload(`/reports/${reportName}/export${query}`, `${reportName}.xlsx`);
      setMessage("Excel export downloaded.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to export report");
    }
  }

  if (!canReadReports) {
    return <div className="error">You do not have permission to view reports.</div>;
  }

  const headers = report?.rows[0] ? Object.keys(report.rows[0]) : [];

  return (
    <section>
      <div className="header">
        <div>
          <h1>Reports</h1>
          <p className="muted">Review fleet KPIs, cost reports, expiry reports, reservations, work orders, and export Excel files.</p>
        </div>
      </div>

      {error && <div className="error spaced">{error}</div>}
      {message && <div className="success spaced">{message}</div>}

      <div className="grid cols-3 spaced">
        {(summary ? Object.entries(summary.kpis).slice(0, 6) : []).map(([key, value]) => (
          <div className="card" key={key}>
            <div className="muted">{humanize(key)}</div>
            <h2>{formatValue(value)}</h2>
          </div>
        ))}
      </div>

      <div className="card filtersGrid spaced">
        <select className="select" value={selectedReport} onChange={(event) => setSelectedReport(event.target.value)}>
          {REPORTS.map((reportOption) => <option key={reportOption.value} value={reportOption.value}>{reportOption.label}</option>)}
        </select>
        <input className="input" type="date" value={filters.from_date} onChange={(event) => setFilters({ ...filters, from_date: event.target.value })} />
        <input className="input" type="date" value={filters.to_date} onChange={(event) => setFilters({ ...filters, to_date: event.target.value })} />
        <input className="input" value={filters.license_plate} onChange={(event) => setFilters({ ...filters, license_plate: event.target.value })} placeholder="Plate" />
        <select className="select" value={filters.vehicle_status} onChange={(event) => setFilters({ ...filters, vehicle_status: event.target.value })}>
          <option value="">All vehicle statuses</option>
          {VEHICLE_STATUSES.map((status) => <option key={status.value} value={status.value}>{status.label}</option>)}
        </select>
        <input className="input" value={filters.department} onChange={(event) => setFilters({ ...filters, department: event.target.value })} placeholder="Department" />
        <input className="input" type="number" value={filters.driver_id} onChange={(event) => setFilters({ ...filters, driver_id: event.target.value })} placeholder="Driver ID" />
        <button className="button" type="button" onClick={() => void loadReports()}>Apply filters</button>
      </div>

      <div className="actions spaced">
        {REPORTS.map((reportOption) => (
          <button key={reportOption.value} className={reportOption.value === selectedReport ? "button smallButton" : "secondaryButton smallButton"} type="button" onClick={() => void exportReport(reportOption.value)}>
            Export {reportOption.label}
          </button>
        ))}
      </div>

      {loading ? <div className="card">Loading report...</div> : (
        <div>
          <div className="header">
            <h2>{REPORTS.find((item) => item.value === selectedReport)?.label}</h2>
            <button className="button" type="button" onClick={() => void exportReport(selectedReport)}>Export selected</button>
          </div>
          <div className="grid cols-3 spaced">
            {report && Object.entries(report.kpis).map(([key, value]) => (
              <div className="card" key={key}>
                <div className="muted">{humanize(key)}</div>
                <h2>{formatValue(value)}</h2>
              </div>
            ))}
          </div>

          <table className="table">
            <thead><tr>{headers.map((header) => <th key={header}>{humanize(header)}</th>)}</tr></thead>
            <tbody>
              {report?.rows.map((row, index) => (
                <tr key={index}>
                  {headers.map((header) => <td key={header}>{formatValue(row[header])}</td>)}
                </tr>
              ))}
              {(!report || report.rows.length === 0) && <tr><td className="muted">No rows match your filters.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
