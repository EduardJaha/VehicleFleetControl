"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import { translateStatus } from "@/i18n/translate";
import type { VehicleAssignment } from "@/lib/types";

type Props = {
  assignments: VehicleAssignment[];
  emptyMessage?: string;
  renderActions?: (assignment: VehicleAssignment) => React.ReactNode;
};

export function AssignmentHistoryTable({ assignments, emptyMessage, renderActions }: Props) {
  const { t } = useTranslation(["modules", "common", "navigation"]);
  const { formatDateTime, formatNumber } = useLanguage();
  const colSpan = renderActions ? 8 : 7;

  return (
    <div className="tableScroll">
      <table className="table assignmentTable">
        <thead>
          <tr>
            <th>{t("modules:vehicleAssignments.vehicleDriver")}</th>
            <th>{t("common:labels.status")}</th>
            <th>{t("modules:vehicleAssignments.schedule")}</th>
            <th>{t("modules:vehicleAssignments.odometerChange")}</th>
            <th>{t("modules:vehicleAssignments.energyChange")}</th>
            <th>{t("modules:vehicleAssignments.purpose")}</th>
            <th>{t("modules:vehicleAssignments.actors")}</th>
            {renderActions && <th>{t("common:labels.actions")}</th>}
          </tr>
        </thead>
        <tbody>
          {assignments.map((assignment) => (
            <tr key={assignment.id}>
              <td>
                <Link className="link stackedLink" href={`/vehicles/${assignment.vehicle_id}`}>
                  {assignment.vehicle_license_plate}
                </Link>
                <span className="muted">{assignment.vehicle_name}</span>
                <Link className="link stackedLink" href={`/drivers/${assignment.driver_id}`}>
                  {assignment.driver_name}
                </Link>
                {assignment.reservation_id && (
                  <span className="muted">#{assignment.reservation_id} · {t("navigation:reservations")}</span>
                )}
              </td>
              <td>
                <span className={assignment.status === "Active" ? "successBadge" : assignment.status === "Overdue" ? "warningBadge" : "badge"}>
                  {assignment.archived ? t("common:labels.archived") : translateStatus(assignment.status)}
                </span>
              </td>
              <td>
                <strong>{formatDateTime(assignment.start_datetime)}</strong>
                <br />
                <span className="muted">{assignment.end_datetime ? formatDateTime(assignment.end_datetime) : "—"}</span>
              </td>
              <td>
                {formatNumber(assignment.start_odometer_km)} km
                <br />
                <span className="muted">
                  {assignment.end_odometer_km == null ? "—" : `${formatNumber(assignment.end_odometer_km)} km`}
                </span>
              </td>
              <td>
                {assignment.start_energy_level == null ? "—" : `${formatNumber(assignment.start_energy_level)}%`}
                <br />
                <span className="muted">
                  {assignment.end_energy_level == null ? "—" : `${formatNumber(assignment.end_energy_level)}%`}
                </span>
              </td>
              <td>
                {assignment.purpose ?? "—"}
                {(assignment.notes || assignment.return_notes) && (
                  <div className="muted assignmentNotes">
                    {assignment.notes ?? assignment.return_notes}
                  </div>
                )}
              </td>
              <td>
                {assignment.assigned_by_name
                  ? t("modules:vehicleAssignments.assignedBy", { name: assignment.assigned_by_name })
                  : t("modules:vehicleAssignments.unassignedActor")}
                <br />
                <span className="muted">
                  {assignment.ended_by_name
                    ? t("modules:vehicleAssignments.endedBy", { name: assignment.ended_by_name })
                    : "—"}
                </span>
              </td>
              {renderActions && <td><div className="actions">{renderActions(assignment)}</div></td>}
            </tr>
          ))}
          {assignments.length === 0 && (
            <tr><td colSpan={colSpan} className="muted">{emptyMessage ?? t("modules:vehicleAssignments.empty")}</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
