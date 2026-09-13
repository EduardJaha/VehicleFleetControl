"use client";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/lib/auth";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import {
  MaintenancePageHeader,
  MaintenanceTable,
} from "@/components/maintenance/Maintenance";
import { SupplyNotice, useSupplyData } from "@/components/supply/shared";

type ReportRow = Record<string, string | number | boolean | null>;
const reports: Array<{ key: string; columns: string[] }> = [
  { key: "inventory-value", columns: ["location_id", "value"] },
  {
    key: "low-stock",
    columns: [
      "part_number",
      "part_name",
      "location_name",
      "quantity_on_hand",
      "reserved_quantity",
      "available_quantity",
      "minimum_stock",
    ],
  },
  {
    key: "parts-consumption",
    columns: ["part_number", "part_name", "quantity", "cost"],
  },
  {
    key: "parts-by-vehicle",
    columns: ["vehicle_id", "part_number", "part_name", "quantity", "cost"],
  },
  {
    key: "vendor-spend",
    columns: [
      "vendor_name",
      "received_parts",
      "external_charges",
      "standalone_services",
      "spend",
    ],
  },
  { key: "purchase-order-status", columns: ["status", "count", "value"] },
  {
    key: "technician-utilization",
    columns: [
      "technician_name",
      "estimated_hours",
      "actual_hours",
      "utilization_percent",
    ],
  },
  { key: "labor-cost", columns: ["technician_name", "hours", "labor_cost"] },
  {
    key: "estimated-vs-actual-labor",
    columns: [
      "work_order_id",
      "estimated_hours",
      "actual_hours",
      "variance_hours",
    ],
  },
  {
    key: "cost-breakdown",
    columns: [
      "work_order_id",
      "vehicle_id",
      "linked_service_id",
      "parts_cost",
      "labor_cost",
      "external_vendor_cost",
      "other_cost",
      "tax_amount",
      "discount_amount",
      "total_actual_cost",
    ],
  },
];
const costs = new Set([
  "value",
  "cost",
  "spend",
  "received_parts",
  "external_charges",
  "standalone_services",
  "labor_cost",
  "parts_cost",
  "external_vendor_cost",
  "other_cost",
  "tax_amount",
  "discount_amount",
  "total_actual_cost",
]);
type Report =
  | ReportRow[]
  | {
      locations?: ReportRow[];
      work_orders?: ReportRow[];
      total_value?: string;
      total_actual_cost?: string;
      service_total?: string;
      unlinked_work_order_total?: string;
      service_adjustments?: string;
    };
export default function SupplyReportsPage() {
  const { t } = useTranslation("modules");
  const text = (key: string) => t(`supply.${key}`);
  const { can } = useAuth();
  const { formatCurrency, formatNumber } = useLanguage();
  const [selected, setSelected] = useState("inventory-value");
  const report = reports.find((r) => r.key === selected)!;
  const result = useSupplyData<Report>(
    `/maintenance/reports/${selected}`,
    [],
    can("reports.view"),
  );
  const data = Array.isArray(result.data)
    ? result.data
    : (result.data.locations ?? result.data.work_orders ?? []);
  if (!can("reports.view"))
    return <p className="card">{text("noPermission")}</p>;
  return (
    <section>
      <MaintenancePageHeader
        title={text("reports")}
        description={text("reportsDescription")}
      />
      <div className="card form spaced">
        <label className="supplyField">
          {text("report")}
          <select
            className="select"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            {reports.map((r) => (
              <option key={r.key} value={r.key}>
                {text(r.key)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <SupplyNotice error={result.error} loading={result.loading} />
      {selected === "technician-utilization" && (
        <p className="muted">{text("utilizationHelp")}</p>
      )}
      {selected === "vendor-spend" && (
        <p className="muted">{text("vendorSpendHelp")}</p>
      )}
      {selected === "cost-breakdown" && (
        <p className="muted">{text("costReportHelp")}</p>
      )}
      {!Array.isArray(result.data) && (
        <div className="dashboardGrid spaced">
          {(
            [
              "total_value",
              "service_total",
              "unlinked_work_order_total",
              "service_adjustments",
              "total_actual_cost",
            ] as const
          )
            .filter(
              (k) =>
                result.data &&
                !Array.isArray(result.data) &&
                result.data[k] !== undefined,
            )
            .map((k) => (
              <div className="card" key={k}>
                <span className="muted">{text(k)}</span>
                <h2>
                  {formatCurrency(
                    !Array.isArray(result.data) ? result.data[k] : 0,
                  )}
                </h2>
              </div>
            ))}
        </div>
      )}
      <div className="card spaced">
        <h2>{text(selected)}</h2>
        <MaintenanceTable>
          <thead>
            <tr>
              {report.columns.map((c) => (
                <th key={c}>{text(c)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((row, n) => (
              <tr key={n}>
                {report.columns.map((c) => (
                  <td key={c}>
                    {row[c] == null
                      ? "—"
                      : costs.has(c)
                        ? formatCurrency(Number(row[c]))
                        : c === "status"
                          ? text(String(row[c]))
                          : typeof row[c] === "number" ||
                              /^-?\d+(\.\d+)?$/.test(String(row[c]))
                            ? formatNumber(Number(row[c]))
                            : String(row[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </MaintenanceTable>
        {!data.length && !result.loading && (
          <p className="muted">{text("empty")}</p>
        )}
      </div>
    </section>
  );
}
