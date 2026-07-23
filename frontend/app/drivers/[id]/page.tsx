"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { AssignmentHistoryTable } from "@/components/assignments/AssignmentHistoryTable";
import { apiGet, vehicleAssignmentsApi } from "@/lib/api";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import { translateStatus } from "@/i18n/translate";
import type { Driver, VehicleAssignment } from "@/lib/types";

type Tab = "overview" | "assignments";

export default function DriverDetailsPage({ params }: { params: { id: string } }) {
  const { t } = useTranslation(["modules", "common"]);
  const { formatDate } = useLanguage();
  const driverId = Number(params.id);
  const [driver, setDriver] = useState<Driver | null>(null);
  const [assignments, setAssignments] = useState<VehicleAssignment[]>([]);
  const [tab, setTab] = useState<Tab>("overview");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      apiGet<Driver>(`/drivers/${driverId}`),
      vehicleAssignmentsApi.list({ driver_id: driverId, page: 1, page_size: 100 })
    ]).then(([driverRow, assignmentRows]) => {
      if (!active) return;
      setDriver(driverRow);
      setAssignments(assignmentRows.items);
    }).catch((err) => {
      if (active) setError(err instanceof Error ? err.message : t("modules:vehicleAssignments.driverLoadError"));
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [driverId, t]);

  if (loading) return <div className="card">{t("common:states.loading")}</div>;
  if (error || !driver) return <div className="error">{error ?? t("modules:vehicleAssignments.driverLoadError")}</div>;

  return (
    <section>
      <div className="header">
        <div>
          <h1>{driver.full_name}</h1>
          <p className="muted">{driver.employee_number} · {driver.department ?? "—"} · {translateStatus(driver.status)}</p>
        </div>
        <Link className="secondaryButton" href="/drivers">{t("modules:vehicleAssignments.backToDrivers")}</Link>
      </div>
      <nav className="vehicleTabs" aria-label={t("modules:vehicleAssignments.driverDetails")}>
        <button className={tab === "overview" ? "vehicleTab active" : "vehicleTab"} type="button" onClick={() => setTab("overview")}>{t("common:labels.details")}</button>
        <button className={tab === "assignments" ? "vehicleTab active" : "vehicleTab"} type="button" onClick={() => setTab("assignments")}>{t("modules:vehicleAssignments.assignmentTab")}</button>
      </nav>
      {tab === "overview" && (
        <div className="detailGrid">
          <section className="card detailCard">
            <h2>{t("modules:vehicleAssignments.driverDetails")}</h2>
            <dl className="detailList">
              <dt>{t("modules:drivers.employeeNumber")}</dt><dd>{driver.employee_number}</dd>
              <dt>{t("common:labels.department")}</dt><dd>{driver.department ?? "—"}</dd>
              <dt>{t("common:labels.email")}</dt><dd>{driver.email ?? "—"}</dd>
              <dt>{t("modules:drivers.phone")}</dt><dd>{driver.phone_number ?? "—"}</dd>
              <dt>{t("common:labels.status")}</dt><dd>{translateStatus(driver.status)}</dd>
            </dl>
          </section>
          <section className="card detailCard">
            <h2>{t("modules:drivers.licence")}</h2>
            <dl className="detailList">
              <dt>{t("modules:drivers.licenceNumber")}</dt><dd>{driver.license_number}</dd>
              <dt>{t("modules:drivers.licenceCategory")}</dt><dd>{driver.license_category}</dd>
              <dt>{t("modules:drivers.licenceExpiry")}</dt><dd>{formatDate(driver.license_expiry_date)}</dd>
              <dt>{t("modules:drivers.assignedVehicle")}</dt><dd>{driver.assigned_license_plate ?? "—"}</dd>
              <dt>{t("common:labels.notes")}</dt><dd>{driver.notes ?? "—"}</dd>
            </dl>
          </section>
        </div>
      )}
      {tab === "assignments" && <AssignmentHistoryTable assignments={assignments} />}
    </section>
  );
}
