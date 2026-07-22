"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import { LinkedRecordCard, MaintenancePageHeader, MaintenanceStatusBadge } from "@/components/maintenance/Maintenance";
import { translateStatus, translateType } from "@/i18n/translate";
import { apiDownloadFile, maintenanceApi } from "@/lib/api";
import type { VehicleServiceDetail } from "@/lib/types";

function Details({ values }: { values: Array<[string, React.ReactNode]> }) {
  return <dl className="detailList">{values.map(([label, value]) => <div style={{ display: "contents" }} key={label}><dt>{label}</dt><dd>{value ?? "-"}</dd></div>)}</dl>;
}

export default function ServiceDetailsPage({ params }: { params: { id: string } }) {
  const { t } = useTranslation(["common", "modules"]);
  const { formatCurrency, formatDate, formatDateTime, formatNumber } = useLanguage();
  const [service, setService] = useState<VehicleServiceDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    maintenanceApi.getService(params.id).then(setService).catch((err) => setError(err instanceof Error ? err.message : t("modules:services.loadError")));
  }, [params.id, t]);

  if (error) return <div className="error">{error}</div>;
  if (!service) return <div className="card">{t("modules:services.loading")}</div>;

  return <section>
    <MaintenancePageHeader
      title={t("modules:services.detailTitle", { id: service.id })}
      description={t("modules:services.detailDescription")}
      actions={<Link className="secondaryButton" href="/services/overview">{t("modules:services.back")}</Link>}
    />
    <div className="actions spaced">
      <MaintenanceStatusBadge status={service.status} />
      <span className="badge">{t("modules:services.sourceBadge", { source: translateType(service.source) })}</span>
    </div>
    <div className="detailGrid spaced">
      <section className="card detailCard"><h2>{t("modules:services.information")}</h2><Details values={[
        [t("modules:services.serviceType"), translateType(service.service_type)],
        [t("modules:services.serviceDate"), formatDate(service.service_date)],
        [t("labels.vehicle"), <Link key="vehicle" className="link" href={`/vehicles/${service.vehicle_id}`}>{service.license_plate}</Link>],
        [t("labels.odometer"), service.odometer_km ? `${formatNumber(service.odometer_km)} km` : "-"],
        [t("labels.workshop"), service.workshop ?? "-"],
        [t("labels.description"), service.description ?? "-"],
      ]} /></section>
      <section className="card detailCard"><h2>{t("modules:services.costInformation")}</h2><Details values={[
        [t("modules:services.laborCost"), formatCurrency(service.labor_cost)],
        [t("modules:services.partsCost"), formatCurrency(service.parts_cost)],
        [t("labels.totalCost"), formatCurrency(service.total_cost)],
      ]} /></section>
      <section className="card detailCard"><h2>{t("modules:services.reminderInformation")}</h2><Details values={[
        [t("modules:services.nextDate"), service.next_service_date ? formatDate(service.next_service_date) : "-"],
        [t("modules:services.nextOdometer"), service.next_service_odometer_km ? `${formatNumber(service.next_service_odometer_km)} km` : "-"],
        [t("modules:services.nextInterval"), service.next_service_km_interval ? `${formatNumber(service.next_service_km_interval)} km` : "-"],
        [t("modules:services.reminderStatus"), service.reminder_status ? <MaintenanceStatusBadge key="reminder-status" status={service.reminder_status} /> : t("modules:services.noReminder")],
      ]} /></section>
      <section className="card detailCard"><h2>{t("modules:services.attachments")}</h2>{service.bills.length
        ? <div className="recordList">{service.bills.map((file) => <div className="recordRow" key={file.id}><div><strong>{translateType(file.attachment_type)}</strong><div className="muted">{t("modules:services.uploaded", { date: formatDateTime(file.uploaded_at) })}</div></div><button className="secondaryButton smallButton" type="button" onClick={() => void apiDownloadFile(file.file_path, `service-${service.id}-attachment`)}>{t("modules:services.downloadFile")}</button></div>)}</div>
        : <div className="maintenanceEmpty muted">{t("modules:services.noAttachments")}</div>}</section>
    </div>
    <section className="card detailCard"><h2>{t("modules:services.sourceInformation")}</h2>{service.linked_work_order
      ? <LinkedRecordCard title={t("modules:services.createdFromWorkOrder", { id: service.linked_work_order.id })} description={`${service.linked_work_order.title} · ${translateStatus(service.linked_work_order.status)}`} href={`/work-orders/${service.linked_work_order.id}`} />
      : <LinkedRecordCard title={t("modules:services.manualSource")} description={t("modules:services.manualSourceDescription")} empty="" />}</section>
  </section>;
}
