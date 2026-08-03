"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { CreateEntityDialog } from "@/components/ui/CreateEntityDialog";
import { EntityPageHeader } from "@/components/ui/EntityPageHeader";
import { VehicleForm, vehicleToPayload } from "@/components/vehicles/VehicleForm";
import { apiDelete, apiDownload, apiGet, apiPost, apiPut, buildQuery, vehicleRegistrationApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { normalizePlateInput } from "@/lib/licensePlates";
import type { ApiMessage, RegistrationCountryCode, RegistrationCountryOption, Vehicle, VehiclePayload } from "@/lib/types";
import { FUEL_TYPES, VEHICLE_STATUS_KEYS, VEHICLE_STATUSES } from "@/lib/constants";
import { useTranslation } from "react-i18next";
import { translateType } from "@/i18n/translate";
import { useLanguage } from "@/components/i18n/LanguageProvider";

export default function VehiclesPage() {
  const { t } = useTranslation(["common", "modules"]);
  const { formatNumber } = useLanguage();
  const { can, user } = useAuth();
  const canWrite = can("vehiclesWrite");
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [isCreateVehicleOpen, setIsCreateVehicleOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [editingVehicle, setEditingVehicle] = useState<Vehicle | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const [updating, setUpdating] = useState(false);
  const [countries, setCountries] = useState<RegistrationCountryOption[]>([]);
  const [filters, setFilters] = useState({ search: "", registration_country: "" as RegistrationCountryCode | "", fuel: "", location: "", status: "", include_archived: false });
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkAction, setBulkAction] = useState("archive");
  const [bulkValue, setBulkValue] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);

  async function loadVehicles(
    status = filters.status,
    includeArchived = filters.include_archived,
    registrationCountry = filters.registration_country,
    search = filters.search
  ) {
    setLoading(true);
    setError(null);
    try {
      const data = await apiGet<Vehicle[]>(`/vehicles${buildQuery({
        status,
        registration_country: registrationCountry,
        search,
        include_archived: includeArchived || undefined
      })}`);
      setVehicles(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:vehicles.loadError"));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadVehicles("");
    void vehicleRegistrationApi.getCountries().then(setCountries).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const locations = useMemo(() => Array.from(new Set(vehicles.map((v) => v.vehicle_location).filter(Boolean))).sort(), [vehicles]);

  const filtered = useMemo(() => {
    const text = filters.search.trim().toLowerCase();
    const normalizedPlate = normalizePlateInput(filters.search);
    return vehicles.filter((vehicle) => {
      const matchesText = !text
        || normalizePlateInput(vehicle.license_plate).includes(normalizedPlate)
        || [vehicle.brand, vehicle.model, vehicle.vehicle_location, vehicle.vin_number ?? ""].some((value) => value.toLowerCase().includes(text));
      const matchesFuel = !filters.fuel || vehicle.fuel_type === filters.fuel;
      const matchesLocation = !filters.location || vehicle.vehicle_location === filters.location;
      return matchesText && matchesFuel && matchesLocation;
    });
  }, [vehicles, filters]);

  function openCreateVehicle() {
    setCreateError(null);
    setMessage(null);
    setIsCreateVehicleOpen(true);
  }

  function closeCreateVehicle() {
    if (submitting) return;
    setCreateError(null);
    setIsCreateVehicleOpen(false);
  }

  async function createVehicle(payload: VehiclePayload) {
    setCreateError(null);
    setMessage(null);
    setSubmitting(true);
    try {
      const created = await apiPost<Vehicle>("/vehicles", payload);
      setMessage(t("modules:vehicles.created", { plate: created.license_plate }));
      setIsCreateVehicleOpen(false);
      await loadVehicles();
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : t("modules:vehicles.createError"));
    } finally {
      setSubmitting(false);
    }
  }

  function openEditVehicle(vehicle: Vehicle) {
    setEditingVehicle(vehicle);
    setEditError(null);
    setMessage(null);
  }

  function closeEditVehicle() {
    if (updating) return;
    setEditError(null);
    setEditingVehicle(null);
  }

  async function updateVehicle(payload: VehiclePayload) {
    if (!editingVehicle) return;
    setEditError(null);
    setMessage(null);
    setUpdating(true);
    try {
      const updated = await apiPut<Vehicle>(`/vehicles/${editingVehicle.id}`, payload);
      setMessage(t("modules:vehicles.updated", { plate: updated.license_plate }));
      setEditingVehicle(null);
      await loadVehicles();
    } catch (err) {
      setEditError(err instanceof Error ? err.message : t("modules:vehicles.updateError"));
    } finally {
      setUpdating(false);
    }
  }

  async function deleteVehicle(vehicle: Vehicle) {
    if (!confirm(t("modules:vehicles.archiveConfirm", { plate: vehicle.license_plate }))) return;
    setError(null);
    setMessage(null);
    try {
      const result = await apiDelete<ApiMessage>(`/vehicles/${vehicle.id}`);
      setMessage(t("modules:vehicles.archived"));
      await loadVehicles();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:vehicles.archiveError"));
    }
  }

  async function restoreVehicle(vehicle: Vehicle) {
    try {
      await apiPost<Vehicle>(`/vehicles/${vehicle.id}/restore`, {});
      setMessage(t("modules:vehicles.restored", { plate: vehicle.license_plate }));
      await loadVehicles();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:vehicles.restoreError"));
    }
  }

  async function applyBulkAction() {
    const ids = Array.from(selected);
    if (!ids.length || !confirm(t("modules:bulk.confirm", { count: ids.length }))) return;
    setBulkBusy(true);
    setError(null);
    try {
      await apiPost<{ affected: number }>("/bulk-actions", {
        entity_type: "Vehicles", action: bulkAction, ids,
        value: bulkValue || null,
        options: bulkAction === "create_work_orders" ? { title: bulkValue || t("modules:bulk.defaultWorkOrder") }
          : bulkAction === "assign_service_program" ? { service_type: bulkValue } : {}
      });
      setMessage(t("modules:bulk.completed", { count: ids.length }));
      setSelected(new Set());
      await loadVehicles();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:bulk.error"));
    } finally {
      setBulkBusy(false);
    }
  }

  return (
    <section>
      <EntityPageHeader
        title={t("modules:vehicles.title")}
        description={t("modules:vehicles.description")}
        actionLabel={canWrite ? t("modules:vehicles.add") : undefined}
        onAction={canWrite ? openCreateVehicle : undefined}
      />

      {canWrite && <CreateEntityDialog
        open={isCreateVehicleOpen}
        title={t("modules:vehicles.add")}
        description={t("modules:vehicles.formDescription")}
        busy={submitting}
        onClose={closeCreateVehicle}
      >
        <VehicleForm
          error={createError}
          submitting={submitting}
          onSubmit={createVehicle}
          onCancel={closeCreateVehicle}
          className="dialogForm"
        />
      </CreateEntityDialog>}

      {canWrite && editingVehicle && <CreateEntityDialog
        open
        title={t("modules:vehicles.edit")}
        description={t("modules:vehicles.editDescription")}
        busy={updating}
        onClose={closeEditVehicle}
      >
        <VehicleForm
          key={editingVehicle.id}
          mode="edit"
          initialValues={vehicleToPayload(editingVehicle)}
          error={editError}
          submitting={updating}
          onSubmit={updateVehicle}
          onCancel={closeEditVehicle}
          className="dialogForm"
        />
      </CreateEntityDialog>}

      <div className="card filtersGrid">
        <input className="input" value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} placeholder={t("modules:vehicles.searchPlaceholder")} />
        <button className="secondaryButton" type="button" onClick={() => void loadVehicles()}>{t("common:actions.search")}</button>
        <select
          className="select"
          aria-label={t("modules:vehicles.registrationCountry")}
          value={filters.registration_country}
          onChange={(e) => {
            const registration_country = e.target.value as RegistrationCountryCode | "";
            setFilters((current) => ({ ...current, registration_country }));
            void loadVehicles(filters.status, filters.include_archived, registration_country);
          }}
        >
          <option value="">{t("modules:vehicles.allCountries")}</option>
          {countries.map((country) => <option key={country.code} value={country.code}>{t(`common:countries.${country.code}`)}</option>)}
        </select>
        <select className="select" value={filters.status} onChange={(e) => { const status = e.target.value; setFilters((current) => ({ ...current, status })); void loadVehicles(status); }}>
          <option value="">{t("modules:vehicles.allStatuses")}</option>
          {VEHICLE_STATUSES.map((status) => <option key={status.value} value={status.value}>{t(`common:${status.labelKey}`)}</option>)}
        </select>
        <select className="select" value={filters.fuel} onChange={(e) => setFilters({ ...filters, fuel: e.target.value })}>
          <option value="">{t("modules:vehicles.allFuelTypes")}</option>
          {FUEL_TYPES.map((fuel) => <option key={fuel} value={fuel}>{translateType(fuel)}</option>)}
        </select>
        <select className="select" value={filters.location} onChange={(e) => setFilters({ ...filters, location: e.target.value })}>
          <option value="">{t("modules:vehicles.allLocations")}</option>
          {locations.map((location) => <option key={location}>{location}</option>)}
        </select>
        {user?.role === "admin" && <label className="actions"><input type="checkbox" checked={filters.include_archived} onChange={(e) => { const include_archived = e.target.checked; setFilters({ ...filters, include_archived }); void loadVehicles(filters.status, include_archived); }} /> {t("modules:vehicles.includeArchived")}</label>}
      </div>

      {error && <div className="error spaced">{error}</div>}
      {message && <div className="success spaced" role="status">{message}</div>}
      {canWrite && <div className="card bulkBar spaced">
        <strong>{t("modules:bulk.selected", { count: selected.size })}</strong>
        <select className="select" value={bulkAction} onChange={(event) => { setBulkAction(event.target.value); setBulkValue(""); }}>
          <option value="archive">{t("modules:bulk.archive")}</option>
          {user?.role === "admin" && <option value="restore">{t("modules:bulk.restore")}</option>}
          <option value="change_status">{t("modules:bulk.changeStatus")}</option>
          <option value="change_location">{t("modules:bulk.changeLocation")}</option>
          <option value="assign_service_program">{t("modules:bulk.assignServiceProgram")}</option>
          <option value="create_work_orders">{t("modules:bulk.createWorkOrders")}</option>
        </select>
        {bulkAction === "change_status" ? <select className="select" value={bulkValue} onChange={(event) => setBulkValue(event.target.value)}><option value="">{t("modules:bulk.chooseValue")}</option>{VEHICLE_STATUSES.map((status) => <option key={status.value} value={status.value}>{t(`common:${status.labelKey}`)}</option>)}</select>
          : ["change_location", "assign_service_program", "create_work_orders"].includes(bulkAction) && <input className="input" value={bulkValue} onChange={(event) => setBulkValue(event.target.value)} placeholder={t(`modules:bulk.placeholders.${bulkAction}`)} />}
        <button className="button" type="button" disabled={!selected.size || bulkBusy || (["change_status", "change_location", "assign_service_program"].includes(bulkAction) && !bulkValue)} onClick={() => void applyBulkAction()}>{t("modules:bulk.apply")}</button>
        <button className="secondaryButton" type="button" disabled={!selected.size} onClick={() => void apiDownload(`/bulk-actions/export?entity_type=Vehicles&ids=${Array.from(selected).join(",")}`, "selected-vehicles.csv")}>{t("modules:bulk.exportSelected")}</button>
      </div>}
      {loading ? <div className="card">{t("modules:vehicles.loading")}</div> : (
        <table className="table">
          <thead>
            <tr>
              {canWrite && <th><input type="checkbox" aria-label={t("modules:bulk.selectAll")} checked={filtered.length > 0 && filtered.every((row) => selected.has(row.id))} onChange={(event) => setSelected(event.target.checked ? new Set(filtered.map((row) => row.id)) : new Set())} /></th>}<th>{t("common:labels.country")}</th><th>{t("common:labels.licencePlate")}</th><th>{t("common:labels.brand")}</th><th>{t("common:labels.model")}</th><th>{t("modules:vehicles.fuel")}</th><th>{t("common:labels.location")}</th><th>{t("common:labels.odometer")}</th><th>{t("common:labels.status")}</th><th>{t("common:labels.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((vehicle) => (
              <tr key={vehicle.id}>
                {canWrite && <td><input type="checkbox" aria-label={t("modules:bulk.selectRow", { name: vehicle.license_plate })} checked={selected.has(vehicle.id)} onChange={(event) => setSelected((current) => { const next = new Set(current); event.target.checked ? next.add(vehicle.id) : next.delete(vehicle.id); return next; })} /></td>}
                <td>{vehicle.registration_country ? t(`common:countries.${vehicle.registration_country}`) : t("modules:vehicles.unresolved")}</td>
                <td><strong>{vehicle.license_plate}</strong></td>
                <td>{vehicle.brand}</td>
                <td>{vehicle.model}</td>
                <td>{translateType(vehicle.fuel_type)}</td>
                <td>{vehicle.vehicle_location}</td>
                <td>{vehicle.odometer_km == null ? "-" : formatNumber(vehicle.odometer_km)}</td>
                <td><span className="badge">{vehicle.archived ? t("common:labels.archived") : VEHICLE_STATUS_KEYS[vehicle.status] ? t(`common:${VEHICLE_STATUS_KEYS[vehicle.status]}`) : vehicle.status_name}</span></td>
                <td>
                    <div className="actions"><Link className="secondaryButton smallButton" href={`/vehicles/${vehicle.id}`}>{t("common:actions.view")}</Link>
                      {canWrite && <>
                      {!vehicle.archived && <><button className="secondaryButton smallButton" type="button" onClick={() => openEditVehicle(vehicle)}>{t("common:actions.edit")}</button>
                      <button className="dangerButton smallButton" type="button" onClick={() => void deleteVehicle(vehicle)}>{t("common:actions.archive")}</button></>}
                      {vehicle.archived && user?.role === "admin" && <button className="secondaryButton smallButton" type="button" onClick={() => void restoreVehicle(vehicle)}>{t("common:actions.restore")}</button>}
                      </>}
                    </div>
                  </td>
              </tr>
            ))}
            {filtered.length === 0 && <tr><td colSpan={canWrite ? 10 : 9} className="muted">{t("modules:vehicles.empty")}</td></tr>}
          </tbody>
        </table>
      )}
    </section>
  );
}
