"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import { maintenanceApi } from "@/lib/api";
import type { Inspection } from "@/lib/types";
import {
  LinkedRecordCard, MaintenancePageHeader, MaintenanceStatusBadge, MaintenanceTable
} from "@/components/maintenance/Maintenance";
import { translateChecklistItem, translateStatus, translateType } from "@/i18n/translate";

export default function InspectionDetailsPage({ params }: { params: { id: string } }) {
  const { formatDate } = useLanguage();
  const { t } = useTranslation(["modules", "common"]);
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    maintenanceApi.getInspection(params.id)
      .then(setInspection)
      .catch((err) => setError(err instanceof Error ? err.message : t("modules:inspections.loadError")));
  }, [params.id, t]);
  if (error) return <div className="error">{error}</div>;
  if (!inspection) return <div className="card">{t("modules:inspections.loading")}</div>;
  const failed = inspection.items.filter((item) => item.status === "Fail");
  return (
    <section>
      <MaintenancePageHeader
        title={`${t("modules:inspections.title")} #${inspection.id}`}
        description={t("modules:inspections.detailsDescription")}
        actions={<Link className="secondaryButton" href="/inspections">{t("modules:inspections.back")}</Link>}
      />
      <div className="detailGrid spaced">
        <section className="card detailCard">
          <h2>{t("modules:inspections.information")}</h2>
          <dl className="detailList">
            <dt>{t("common:labels.vehicle")}</dt><dd><Link className="link" href={`/vehicles/${inspection.vehicle_id}`}>{inspection.license_plate}</Link></dd>
            <dt>{t("common:labels.driver")}</dt><dd>{inspection.driver_name ?? inspection.driver_id ?? "-"}</dd>
            <dt>{t("modules:inspections.inspectionType")}</dt><dd>{translateType(inspection.inspection_type)}</dd>
            <dt>{t("modules:inspections.inspectionDate")}</dt><dd>{formatDate(inspection.inspection_date)}</dd>
            <dt>{t("modules:inspections.overallStatus")}</dt><dd><MaintenanceStatusBadge status={inspection.overall_status} /></dd>
            <dt>{t("modules:inspections.inspector")}</dt><dd>{inspection.inspector ?? "-"}</dd>
            <dt>{t("common:labels.notes")}</dt><dd>{inspection.notes ?? "-"}</dd>
          </dl>
        </section>
        <section className="card detailCard">
          <h2>{t("modules:inspections.relatedMaintenance")}</h2>
          <LinkedRecordCard
            title={inspection.linked_work_order
              ? t("modules:inspections.workOrderCreated", { id: inspection.linked_work_order.id })
              : t("modules:inspections.createdWorkOrder")}
            description={inspection.linked_work_order
              ? `${inspection.linked_work_order.title} · ${translateStatus(inspection.linked_work_order.status)}`
              : undefined}
            href={inspection.linked_work_order ? `/work-orders/${inspection.linked_work_order.id}` : undefined}
            empty={t("modules:inspections.noneCreated")}
          />
          {failed.length > 0 && !inspection.linked_work_order && (
            <div className="actions" style={{ marginTop: 14 }}>
              <Link className="button" href={`/work-orders?inspection_id=${inspection.id}&license_plate=${encodeURIComponent(inspection.license_plate)}`}>
                {t("modules:workOrders.create")}
              </Link>
            </div>
          )}
        </section>
      </div>
      <section className="card detailCard">
        <h2>{t("modules:inspections.checklist")}</h2>
        <MaintenanceTable>
          <thead><tr><th>{t("modules:inspections.item")}</th><th>{t("common:labels.status")}</th><th>{t("common:labels.comment")}</th></tr></thead>
          <tbody>{inspection.items.map((item) => (
            <tr key={item.id ?? item.item_name} className={item.status === "Fail" ? "criticalRow" : undefined}>
              <td>{translateChecklistItem(item.item_name)}</td>
              <td><MaintenanceStatusBadge status={item.status} /></td>
              <td>{item.comment ?? "-"}</td>
            </tr>
          ))}</tbody>
        </MaintenanceTable>
      </section>
    </section>
  );
}
