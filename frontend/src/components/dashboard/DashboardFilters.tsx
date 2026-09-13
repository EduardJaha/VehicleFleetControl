"use client";

import { useTranslation } from "react-i18next";
import type { DashboardFilterOption } from "@/lib/types";

export type DashboardFilterState = {
  period: string;
  fromDate: string;
  toDate: string;
  locationId: string;
  departmentId: string;
  costCenterId: string;
};

type Props = {
  value: DashboardFilterState;
  options: { locations: DashboardFilterOption[]; departments: DashboardFilterOption[]; cost_centers: DashboardFilterOption[] };
  disabled?: boolean;
  onChange: (next: DashboardFilterState) => void;
};

const PERIODS = ["today", "last_7_days", "this_month", "last_month", "this_quarter", "this_year", "custom"];

export function DashboardFilters({ value, options, disabled, onChange }: Props) {
  const { t } = useTranslation(["modules", "common"]);
  const set = (key: keyof DashboardFilterState, nextValue: string) => onChange({ ...value, [key]: nextValue });

  return (
    <div className="card dashboardFilters" aria-label={t("modules:dashboard.filters.title")}>
      <label>
        <span>{t("modules:dashboard.filters.period")}</span>
        <select className="select" value={value.period} disabled={disabled} onChange={(event) => set("period", event.target.value)}>
          {PERIODS.map((period) => <option key={period} value={period}>{t(`modules:dashboard.periods.${period}`)}</option>)}
        </select>
      </label>
      {value.period === "custom" && <>
        <label>
          <span>{t("common:labels.startDate")}</span>
          <input className="input" type="date" value={value.fromDate} max={value.toDate || undefined} disabled={disabled} onChange={(event) => set("fromDate", event.target.value)} />
        </label>
        <label>
          <span>{t("common:labels.endDate")}</span>
          <input className="input" type="date" value={value.toDate} min={value.fromDate || undefined} disabled={disabled} onChange={(event) => set("toDate", event.target.value)} />
        </label>
      </>}
      <label>
        <span>{t("common:labels.location")}</span>
        <select className="select" value={value.locationId} disabled={disabled} onChange={(event) => set("locationId", event.target.value)}>
          <option value="">{t("common:labels.all")}</option>
          {options.locations.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
      <label>
        <span>{t("common:labels.department")}</span>
        <select className="select" value={value.departmentId} disabled={disabled} onChange={(event) => set("departmentId", event.target.value)}>
          <option value="">{t("common:labels.all")}</option>
          {options.departments.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
      <label>
        <span>{t("modules:dashboard.filters.costCenter")}</span>
        <select className="select" value={value.costCenterId} disabled={disabled} onChange={(event) => set("costCenterId", event.target.value)}>
          <option value="">{t("common:labels.all")}</option>
          {options.cost_centers.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
      <button className="linkButton dashboardClearFilters" type="button" disabled={disabled} onClick={() => onChange({ period: "this_month", fromDate: "", toDate: "", locationId: "", departmentId: "", costCenterId: "" })}>
        {t("common:actions.clearFilters")}
      </button>
    </div>
  );
}
