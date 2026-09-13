"use client";

import Link from "next/link";
import { WorkOrderWorkspace } from "@/components/supply/WorkOrderWorkspace";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { maintenanceApi } from "@/lib/api";
import type { WorkOrder } from "@/lib/types";
import {
  LinkedRecordCard, MaintenancePageHeader, MaintenancePriorityBadge, MaintenanceStatusBadge
} from "@/components/maintenance/Maintenance";
import { CompleteWorkOrderDialog } from "@/components/maintenance/CompleteWorkOrderDialog";
import { useAuth } from "@/lib/auth";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import { translateStatus, translateType } from "@/i18n/translate";

function Details({ values }: { values: Array<[string, React.ReactNode]> }) {
  return <dl className="detailList">{values.map(([label, value]) => <div key={label} style={{ display: "contents" }}><dt>{label}</dt><dd>{value ?? "-"}</dd></div>)}</dl>;
}

export default function WorkOrderDetailsPage({ params }: { params: { id: string } }) {
  const { t } = useTranslation(["modules", "common"]);
  const { formatCurrency, formatDate, formatDateTime, formatNumber } = useLanguage();
  const [order, setOrder] = useState<WorkOrder | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [completionOpen, setCompletionOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const { can } = useAuth();
  const load = () => maintenanceApi.getWorkOrder(params.id)
    .then(setOrder)
    .catch((err) => setError(err instanceof Error ? err.message : t("modules:workOrders.loadError")));
  useEffect(() => { void load(); }, [params.id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (error) return <div className="error">{error}</div>;
  if (!order) return <div className="card">{t("modules:workOrders.loading")}</div>;
  return (
    <section>
      <MaintenancePageHeader
        title={`${t("modules:workOrders.workOrder")} #${order.id}`}
        description={t("modules:workOrders.detailsDescription")}
        actions={<Link className="secondaryButton" href="/work-orders">{t("modules:workOrders.back")}</Link>}
      />
      {message && <div className="success spaced">{message}</div>}
      <div className="actions spaced">
        <MaintenanceStatusBadge status={order.status} />
        <MaintenancePriorityBadge priority={order.priority} />
        <span className="badge">{t("common:labels.source")}: {translateType(order.source)}</span>
      </div>
      {can("maintenance.complete_work_order") && !order.archived && !["Completed", "Cancelled"].includes(order.status) && (
        <div className="actions spaced"><button className="button" type="button" onClick={() => setCompletionOpen(true)}>{t("modules:workOrders.complete")}</button></div>
      )}
      <WorkOrderWorkspace order={order} onChange={load}>
      <div className="detailGrid spaced">
        <section className="card detailCard">
          <h2>{t("modules:workOrders.information")}</h2>
          <Details values={[
            ["ID", `#${order.id}`],
            [t("common:labels.description"), order.title],
            [t("common:labels.details"), order.description ?? "-"],
            [t("modules:workOrders.reportedIssue"), order.reported_issue ?? "-"],
            [t("common:labels.vehicle"), <Link key="vehicle" className="link" href={`/vehicles/${order.vehicle_id}`}>{order.license_plate}</Link>],
            [t("common:labels.priority"), <MaintenancePriorityBadge key="priority" priority={order.priority} />],
            [t("common:labels.status"), <MaintenanceStatusBadge key="status" status={order.status} />],
            [t("common:labels.source"), translateType(order.source)],
            [t("common:labels.created"), formatDateTime(order.created_at)],
            [t("modules:workOrders.expectedCompletion"), order.expected_completion_date ? formatDate(order.expected_completion_date) : "-"],
            [t("modules:workOrders.actualCompletion"), order.actual_completion_date ? formatDate(order.actual_completion_date) : "-"]
          ]} />
        </section>
        <section className="card detailCard">
          <h2>{t("modules:workOrders.assignmentInformation")}</h2>
          <Details values={[
            [t("modules:workOrders.assignedPerson"), order.assigned_to ?? order.driver_name ?? "-"],
            [t("common:labels.workshop"), order.workshop ?? "-"],
            [t("modules:workOrders.requestedBy"), order.requested_by ?? "-"],
            [t("modules:workOrders.createdBy"), order.created_by ?? t("modules:workOrders.legacyRecord")]
          ]} />
        </section>
        <section className="card detailCard">
          <h2>{t("modules:workOrders.costInformation")}</h2>
          <Details values={[
            [t("modules:workOrders.laborCost"), formatCurrency(order.labor_cost)],
            [t("modules:workOrders.partsCost"), formatCurrency(order.parts_cost)],
            [t("modules:supply.external_vendor_cost"), formatCurrency(order.external_vendor_cost)],
            [t("modules:supply.other_cost"), formatCurrency(order.other_cost)],
            [t("modules:supply.tax_amount"), formatCurrency(order.tax_amount)],
            [t("modules:supply.discount_amount"), formatCurrency(order.discount_amount)],
            [t("common:labels.totalCost"), formatCurrency(order.total_cost)]
          ]} />
        </section>
        <section className="card detailCard">
          <h2>{t("modules:workOrders.completionInformation")}</h2>
          <Details values={[
            [t("modules:workOrders.completedOdometer"), order.completed_odometer_km ? `${formatNumber(order.completed_odometer_km)} km` : "-"],
            [t("modules:workOrders.completionDate"), order.actual_completion_date ? formatDate(order.actual_completion_date) : "-"],
            [t("modules:workOrders.completionNotes"), order.completion_notes ?? "-"],
            [t("modules:workOrders.completedBy"), order.completed_by ?? "-"]
          ]} />
        </section>
      </div>
      <section className="card detailCard">
        <h2>{t("modules:workOrders.relatedRecords")}</h2>
        <div className="linkedRecords">
          <LinkedRecordCard
            title={t("modules:workOrders.sourceInspection")}
            description={order.source_inspection ? `${translateType(order.source_inspection.inspection_type)} · ${translateStatus(order.source_inspection.overall_status)}` : undefined}
            href={order.source_inspection ? `/inspections/${order.source_inspection.id}` : undefined}
            empty={t("modules:workOrders.noSourceInspection")}
          />
          <LinkedRecordCard
            title={t("modules:workOrders.sourceReminder")}
            description={order.source_reminder ? `${translateType(order.source_reminder.service_type)} · ${translateStatus(order.source_reminder.status)}` : undefined}
            href={order.source_reminder ? `/services/reminders?reminder_id=${order.source_reminder.id}` : undefined}
            empty={t("modules:workOrders.noSourceReminder")}
          />
          <LinkedRecordCard
            title={t("modules:workOrders.linkedService")}
            description={order.linked_service ? `${translateType(order.linked_service.service_type)} · ${formatDate(order.linked_service.service_date)}` : undefined}
            href={order.linked_service ? `/services/${order.linked_service.id}` : undefined}
            empty={t("modules:workOrders.noLinkedService")}
          />
        </div>
        {!order.linked_service && order.status === "Completed" && (
          <div className="actions" style={{ marginTop: 14 }}>
            <Link className="button" href={`/services/overview?work_order_id=${order.id}&license_plate=${encodeURIComponent(order.license_plate)}`}>
              {t("modules:workOrders.createLinkedService")}
            </Link>
          </div>
        )}
      </section>
      </WorkOrderWorkspace>
      <CompleteWorkOrderDialog
        order={order}
        open={completionOpen}
        onClose={() => setCompletionOpen(false)}
        onCompleted={async (completed, uploadWarning) => {
          setMessage(uploadWarning ?? t("modules:workOrders.completedMessage", { id: completed.work_order.id }));
          await load();
        }}
      />
    </section>
  );
}
