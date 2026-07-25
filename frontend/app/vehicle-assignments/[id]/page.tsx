"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { AssignmentHistoryTable } from "@/components/assignments/AssignmentHistoryTable";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import { filesApi, vehicleAssignmentsApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Attachment, VehicleAssignment } from "@/lib/types";

export default function VehicleAssignmentDetailsPage({ params }: { params: { id: string } }) {
  const { t } = useTranslation(["modules", "common"]);
  const { formatDateTime, formatNumber } = useLanguage();
  const { can } = useAuth();
  const [assignment, setAssignment] = useState<VehicleAssignment | null>(null);
  const [attachments, setAttachments] = useState<Record<number, Attachment[]>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void Promise.all([
      vehicleAssignmentsApi.get(params.id),
      vehicleAssignmentsApi.conditions(params.id)
    ])
      .then(async ([row, conditions]) => {
        setAssignment({ ...row, conditions });
        const fileGroups = await Promise.all(
          conditions.map(async (condition) => [
            condition.id,
            await filesApi.list("VehicleConditionRecord", condition.id)
          ] as const)
        );
        setAttachments(Object.fromEntries(fileGroups));
      })
      .catch((err) => setError(err instanceof Error ? err.message : t("modules:vehicleAssignments.loadError")));
  }, [params.id, t]);

  return (
    <section>
      <div className="header">
        <div>
          <Link className="link" href="/vehicle-assignments">← {t("modules:vehicleAssignments.assignmentHistory")}</Link>
          <h1>{t("modules:vehicleAssignments.assignmentDetails", { id: params.id })}</h1>
          <p className="muted">{t("modules:vehicleAssignments.assignmentDetailsDescription")}</p>
        </div>
        {assignment && can("vehicleAssignmentsWrite") && (
          <div className="actions">
            {assignment.status === "Scheduled" && (
              <Link className="button" href={`/vehicle-assignments?checkout=1&assignment_id=${assignment.id}&vehicle_id=${assignment.vehicle_id}&driver_id=${assignment.driver_id}${assignment.reservation_id ? `&reservation_id=${assignment.reservation_id}` : ""}`}>
                {t("modules:vehicleAssignments.checkOutVehicle")}
              </Link>
            )}
            {["Active", "Overdue"].includes(assignment.status) && (
              <>
                <Link className="button" href={`/vehicle-assignments?return_id=${assignment.id}`}>{t("modules:vehicleAssignments.returnVehicle")}</Link>
                <Link className="secondaryButton" href={`/vehicle-assignments?return_id=${assignment.id}&damage=1`}>{t("modules:vehicleAssignments.reportDamage")}</Link>
                <Link className="secondaryButton" href={`/vehicle-assignments?return_id=${assignment.id}&inspection=1`}>{t("modules:vehicleAssignments.createReturnInspection")}</Link>
              </>
            )}
          </div>
        )}
      </div>
      {error && <div className="error spaced">{error}</div>}
      {!assignment && !error && <div className="card">{t("common:states.loading")}</div>}
      {assignment && (
        <>
          <AssignmentHistoryTable assignments={[assignment]} />
          <div className="grid cols-2 spaced">
            {assignment.conditions.map((condition) => (
              <article className="card" key={condition.id}>
                <h2>{condition.record_type === "Checkout" ? t("modules:vehicleAssignments.checkOutVehicle") : t("modules:vehicleAssignments.returnVehicle")}</h2>
                <p><strong>{formatDateTime(condition.recorded_at)}</strong></p>
                <p>{t("modules:vehicleAssignments.vehicleCondition")}: <strong>{condition.vehicle_condition}</strong></p>
                <p>{t("modules:vehicleAssignments.odometer")}: <strong>{formatNumber(condition.odometer_km)} km</strong></p>
                <p>{t("modules:vehicleAssignments.energy")}: <strong>{condition.energy_level == null ? "—" : `${formatNumber(condition.energy_level)}%`}</strong></p>
                {condition.damage_description && <p>{condition.damage_description}</p>}
                {condition.driver_comments && <p className="muted">{condition.driver_comments}</p>}
                <p className="muted">{t("modules:vehicleAssignments.attachmentCount", { count: condition.attachment_count })}</p>
                {(attachments[condition.id] ?? []).map((file) => (
                  <button className="secondaryButton smallButton" type="button" key={file.id} onClick={() => void filesApi.download(file)}>
                    {file.original_filename}
                  </button>
                ))}
              </article>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
