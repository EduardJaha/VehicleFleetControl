"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { CreateEntityDialog } from "@/components/ui/CreateEntityDialog";
import { EntityPageHeader } from "@/components/ui/EntityPageHeader";
import { SearchableCombobox } from "@/components/ui/SearchableCombobox";
import { apiDelete, apiDownloadFile, apiGet, apiPostForm, apiPut } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { FUEL_TYPES } from "@/lib/constants";
import {
  calculationDescription,
  formatEnergyQuantity,
  formatEnergyUnitPrice,
  quantityLabel,
  stationLabel,
  unitCostLabel
} from "@/lib/energy";
import { toApiDate, toInputDate, todayInputDate } from "@/lib/format";
import type { ApiMessage, EnergyUnit, FuelRecord, Vehicle } from "@/lib/types";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import { translateType } from "@/i18n/translate";

type FuelForm = {
  vehicle_id: number | null;
  refuel_date: string;
  quantity: string;
  unit_cost: string;
  location: string;
  station_name: string;
  odometer_km: string;
};

type FuelEditForm = Omit<FuelForm, "vehicle_id">;

function emptyFuelForm(): FuelForm {
  return {
    vehicle_id: null,
    refuel_date: todayInputDate(),
    quantity: "",
    unit_cost: "",
    location: "",
    station_name: "",
    odometer_km: ""
  };
}

function unitForVehicle(vehicle: Vehicle | undefined): EnergyUnit | null {
  if (!vehicle) return null;
  return vehicle.fuel_type.toLowerCase() === "electric" ? "KWH" : "L";
}

function calculatedCost(quantity: string, unitCost: string): string {
  const quantityValue = Number(quantity);
  const unitCostValue = Number(unitCost);
  if (!(quantityValue > 0) || !(unitCostValue >= 0) || unitCost === "") return "";
  return (quantityValue * unitCostValue).toFixed(2);
}

export default function FuelPage() {
  const { t } = useTranslation(["modules", "common"]);
  const { language, formatDate, formatNumber, formatCurrency } = useLanguage();
  const { can } = useAuth();
  const canCreate = can("fuel.create");
  const canEdit = can("fuel.edit") && can("fuel.view_cost");
  const canViewCost = can("fuel.view_cost");
  const [records, setRecords] = useState<FuelRecord[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [loading, setLoading] = useState(true);
  const [vehiclesLoading, setVehiclesLoading] = useState(true);
  const [vehiclesError, setVehiclesError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [form, setForm] = useState<FuelForm>(emptyFuelForm);
  const [billFile, setBillFile] = useState<File | null>(null);
  const [isFuelDialogOpen, setIsFuelDialogOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<FuelEditForm | null>(null);
  const [filters, setFilters] = useState({
    search: "",
    fuel_type: "",
    location: "",
    station: "",
    from_date: "",
    to_date: ""
  });

  async function loadFuelRecords() {
    setLoading(true);
    setError(null);
    try {
      setRecords(await apiGet<FuelRecord[]>("/fuel/all"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:fuel.loadError"));
    } finally {
      setLoading(false);
    }
  }

  async function loadVehicles() {
    setVehiclesLoading(true);
    setVehiclesError(null);
    try {
      setVehicles(await apiGet<Vehicle[]>("/vehicles"));
    } catch (err) {
      setVehiclesError(err instanceof Error ? err.message : t("modules:fuel.vehiclesLoadError"));
    } finally {
      setVehiclesLoading(false);
    }
  }

  useEffect(() => {
    void loadFuelRecords();
    void loadVehicles();
  }, []);

  const selectedVehicle = useMemo(
    () => vehicles.find((vehicle) => vehicle.id === form.vehicle_id),
    [form.vehicle_id, vehicles]
  );
  const selectedUnit = unitForVehicle(selectedVehicle);
  const vehicleOptions = useMemo(
    () => vehicles.map((vehicle) => ({
      id: vehicle.id,
      name: `${vehicle.license_plate} — ${vehicle.brand} ${vehicle.model} — ${translateType(vehicle.fuel_type)}`
    })),
    [language, vehicles]
  );
  const locations = useMemo(
    () => Array.from(new Set(records.map((record) => record.location).filter(Boolean))).sort(),
    [records]
  );
  const calculatedTotal = useMemo(
    () => calculatedCost(form.quantity, form.unit_cost),
    [form.quantity, form.unit_cost]
  );

  const filtered = useMemo(() => {
    const text = filters.search.trim().toLowerCase();
    const from = filters.from_date ? new Date(filters.from_date) : null;
    const to = filters.to_date ? new Date(filters.to_date) : null;
    return records.filter((record) => {
      const inputDate = toInputDate(record.refuel_date);
      const recordDate = inputDate ? new Date(inputDate) : null;
      const matchesText = !text || [
        record.license_plate,
        record.brand,
        record.model,
        record.location,
        record.station_name
      ].some((value) => value.toLowerCase().includes(text));
      const matchesFuel = !filters.fuel_type || record.fuel_type === filters.fuel_type;
      const matchesLocation = !filters.location || record.location === filters.location;
      const matchesStation = !filters.station || record.station_name.toLowerCase().includes(filters.station.toLowerCase());
      const matchesFrom = !from || (recordDate && recordDate >= from);
      const matchesTo = !to || (recordDate && recordDate <= to);
      return matchesText && matchesFuel && matchesLocation && matchesStation && matchesFrom && matchesTo;
    });
  }, [records, filters]);

  function selectVehicle(vehicleId: number | null) {
    const vehicle = vehicles.find((candidate) => candidate.id === vehicleId);
    setForm((current) => ({
      ...current,
      vehicle_id: vehicleId,
      quantity: "",
      unit_cost: "",
      location: vehicle?.vehicle_location ?? "",
      station_name: "",
      odometer_km: ""
    }));
    setError(null);
  }

  async function registerFuel(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedVehicle || !selectedUnit) {
      setError(t("modules:fuel.selectVehicle"));
      return;
    }
    setError(null);
    setMessage(null);
    setSubmitting(true);
    try {
      const data = new FormData();
      data.append("vehicle_id", String(selectedVehicle.id));
      data.append("refuel_date", toApiDate(form.refuel_date));
      data.append("quantity", form.quantity);
      if (form.unit_cost) data.append("unit_cost", form.unit_cost);
      if (form.location) data.append("location", form.location);
      if (form.station_name) data.append("station_name", form.station_name);
      if (form.odometer_km) data.append("odometer_km", form.odometer_km);
      if (billFile) data.append("bill_file", billFile);
      const result = await apiPostForm<{ message?: string }>("/fuel", data);
      setMessage(t("modules:fuel.saved"));
      setForm(emptyFuelForm());
      setBillFile(null);
      setIsFuelDialogOpen(false);
      await loadFuelRecords();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:fuel.saveError"));
    } finally {
      setSubmitting(false);
    }
  }

  function openFuelDialog() {
    setForm(emptyFuelForm());
    setBillFile(null);
    setError(null);
    setMessage(null);
    setIsFuelDialogOpen(true);
  }

  function closeFuelDialog() {
    if (submitting) return;
    setForm(emptyFuelForm());
    setBillFile(null);
    setError(null);
    setIsFuelDialogOpen(false);
  }

  function startEdit(record: FuelRecord) {
    setEditingId(record.id);
    setEditForm({
      refuel_date: toInputDate(record.refuel_date),
      quantity: String(record.quantity ?? ""),
      unit_cost: String(record.unit_cost ?? ""),
      location: record.location ?? "",
      station_name: record.station_name ?? "",
      odometer_km: String(record.odometer_km ?? "")
    });
  }

  async function saveEdit(recordId: number) {
    if (!editForm) return;
    setError(null);
    setMessage(null);
    try {
      const result = await apiPut<ApiMessage>(`/fuel/${recordId}`, {
        refuel_date: toApiDate(editForm.refuel_date),
        quantity: Number(editForm.quantity),
        unit_cost: editForm.unit_cost ? Number(editForm.unit_cost) : 0,
        location: editForm.location,
        station_name: editForm.station_name,
        odometer_km: editForm.odometer_km ? Number(editForm.odometer_km) : null
      });
      setMessage(t("modules:fuel.updated"));
      setEditingId(null);
      setEditForm(null);
      await loadFuelRecords();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:fuel.updateError"));
    }
  }

  async function deleteFuel(record: FuelRecord) {
    if (!confirm(t("modules:fuel.archiveConfirm", { kind: t(`modules:fuel.${record.fuel_type === "Electric" ? "charging" : "fuel"}`), plate: record.license_plate, date: record.refuel_date }))) return;
    setError(null);
    setMessage(null);
    try {
      const result = await apiDelete<ApiMessage>(`/fuel/${record.id}`);
      setMessage(t("modules:fuel.archived"));
      await loadFuelRecords();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:fuel.archiveError"));
    }
  }

  return (
    <section>
      <EntityPageHeader
        title={t("modules:fuel.title")}
        description={t("modules:fuel.description")}
        actionLabel={canCreate ? t("modules:fuel.add") : undefined}
        onAction={canCreate ? openFuelDialog : undefined}
      />
      {error && !isFuelDialogOpen && <div className="error spaced" role="alert">{error}</div>}
      {message && <div className="success spaced" role="status">{message}</div>}

      {canCreate && <CreateEntityDialog
        open={isFuelDialogOpen}
        title={t("modules:fuel.add")}
        description={t("modules:fuel.formDescription")}
        busy={submitting}
        onClose={closeFuelDialog}
      >
        <form onSubmit={registerFuel} className="form dialogForm">
          {error && <div className="error" role="alert">{error}</div>}
          <div className="formGrid">
            <div className="formRow span2">
              <label htmlFor="fuel-vehicle">{t("common:labels.vehicle")}</label>
              <SearchableCombobox
                id="fuel-vehicle"
                options={vehicleOptions}
                value={form.vehicle_id}
                onChange={selectVehicle}
                placeholder={t("modules:fuel.vehicleSearch")}
                searchPlaceholder={t("modules:fuel.vehicleSearchType")}
                emptyText={t("modules:fuel.noVehicle")}
                loadingText={t("modules:fuel.loadingVehicles")}
                loading={vehiclesLoading}
                error={vehiclesError}
                required
              />
            </div>

            <div className="formRow">
              <label>{t(`modules:fuel.${selectedUnit === "KWH" ? "energyType" : "fuelType"}`)}</label>
              <div className="input" aria-label={t(`modules:fuel.${selectedUnit === "KWH" ? "energyType" : "fuelType"}`)}>
                {selectedVehicle ? translateType(selectedVehicle.fuel_type) : t("modules:fuel.selectVehicleFirst")}
              </div>
            </div>
            <div className="formRow">
              <label htmlFor="fuel-refuel-date">{t("modules:fuel.date")}</label>
              <input id="fuel-refuel-date" className="input" type="date" value={form.refuel_date} onChange={(event) => setForm({ ...form, refuel_date: event.target.value })} required />
            </div>

            {selectedVehicle && <div className="card span2">
              <div className="muted">{t("modules:fuel.selectedVehicle")}</div>
              <strong>{selectedVehicle.license_plate}</strong>
              <div>{selectedVehicle.brand} {selectedVehicle.model}</div>
              <div>{t(`modules:fuel.${selectedUnit === "KWH" ? "energyType" : "fuelType"}`)}: {translateType(selectedVehicle.fuel_type)}</div>
              <div>{t("common:labels.odometer")}: {formatNumber(selectedVehicle.odometer_km ?? 0)} km</div>
              <div>{t("common:labels.location")}: {selectedVehicle.vehicle_location}</div>
            </div>}

            <div className="formRow">
              <label htmlFor="fuel-quantity">{selectedUnit ? quantityLabel(selectedUnit) : t("modules:fuel.quantity")}</label>
              <input
                id="fuel-quantity"
                className="input"
                type="number"
                min="0.001"
                step="0.001"
                value={form.quantity}
                onChange={(event) => setForm({ ...form, quantity: event.target.value })}
                placeholder={selectedUnit ? undefined : t("modules:fuel.selectVehicleFirst")}
                disabled={!selectedVehicle}
                required
              />
            </div>
            <div className="formRow">
              <label htmlFor="fuel-unit-cost">{selectedUnit ? unitCostLabel(selectedUnit) : t("modules:fuel.unitCost")}</label>
              <input
                id="fuel-unit-cost"
                className="input"
                type="number"
                min="0"
                step="0.0001"
                value={form.unit_cost}
                onChange={(event) => setForm({ ...form, unit_cost: event.target.value })}
                placeholder={selectedUnit ? undefined : t("modules:fuel.selectVehicleFirst")}
                disabled={!selectedVehicle}
                required
              />
            </div>
            <div className="formRow">
              <label htmlFor="fuel-total-cost">{t("modules:fuel.calculatedTotal")}</label>
              <input
                id="fuel-total-cost"
                className="input"
                value={calculatedTotal}
                placeholder={selectedUnit ? calculationDescription(selectedUnit) : t("modules:fuel.selectVehicleFirst")}
                readOnly
              />
            </div>
            <div className="formRow">
              <label htmlFor="fuel-odometer">{t("modules:vehicles.odometerKm")}</label>
              <input
                id="fuel-odometer"
                className="input"
                type="number"
                min={selectedVehicle?.odometer_km ?? 0}
                value={form.odometer_km}
                onChange={(event) => setForm({ ...form, odometer_km: event.target.value })}
                placeholder={selectedVehicle ? t("modules:fuel.currentOdometer", { value: formatNumber(selectedVehicle.odometer_km ?? 0) }) : t("modules:fuel.selectVehicleFirst")}
                disabled={!selectedVehicle}
              />
            </div>
            <div className="formRow">
              <label htmlFor="fuel-location">{t("common:labels.location")}</label>
              <input id="fuel-location" className="input" value={form.location} onChange={(event) => setForm({ ...form, location: event.target.value })} disabled={!selectedVehicle} />
            </div>
            <div className="formRow">
              <label htmlFor="fuel-station">{selectedUnit ? stationLabel(selectedUnit) : t("modules:fuel.stationProvider")}</label>
              <input id="fuel-station" className="input" value={form.station_name} onChange={(event) => setForm({ ...form, station_name: event.target.value })} disabled={!selectedVehicle} />
            </div>
            <div className="formRow span2">
              <label htmlFor="fuel-bill-file">{t("modules:fuel.billOptional")}</label>
              <input id="fuel-bill-file" className="input" type="file" onChange={(event) => setBillFile(event.target.files?.[0] ?? null)} disabled={!selectedVehicle} />
            </div>
          </div>
          <div className="actions dialogActions">
            <button className="secondaryButton" type="button" onClick={closeFuelDialog} disabled={submitting}>{t("common:actions.cancel")}</button>
            <button className="button" type="submit" disabled={submitting || !selectedVehicle}>{submitting ? t("modules:fuel.saving") : t("modules:fuel.save")}</button>
          </div>
        </form>
      </CreateEntityDialog>}

      <div className="card filtersGrid spaced">
        <input className="input" value={filters.search} onChange={(event) => setFilters({ ...filters, search: event.target.value })} placeholder={t("modules:fuel.searchPlaceholder")} />
        <select className="select" value={filters.fuel_type} onChange={(event) => setFilters({ ...filters, fuel_type: event.target.value })}>
          <option value="">{t("modules:fuel.allTypes")}</option>
          {FUEL_TYPES.map((fuel) => <option key={fuel} value={fuel}>{translateType(fuel)}</option>)}
        </select>
        <select className="select" value={filters.location} onChange={(event) => setFilters({ ...filters, location: event.target.value })}>
          <option value="">{t("modules:fuel.allLocations")}</option>
          {locations.map((location) => <option key={location}>{location}</option>)}
        </select>
        <input className="input" value={filters.station} onChange={(event) => setFilters({ ...filters, station: event.target.value })} placeholder={t("modules:fuel.stationProvider")} />
        <input className="input" type="date" value={filters.from_date} onChange={(event) => setFilters({ ...filters, from_date: event.target.value })} />
        <input className="input" type="date" value={filters.to_date} onChange={(event) => setFilters({ ...filters, to_date: event.target.value })} />
      </div>

      {loading ? <div className="card">{t("modules:fuel.loading")}</div> : (
        <table className="table">
          <thead>
            <tr>
              <th>{t("common:labels.licencePlate")}</th><th>{t("common:labels.vehicle")}</th><th>{t("common:labels.date")}</th><th>{t("modules:fuel.type")}</th>
              <th>{t("common:labels.quantity")}</th>{canViewCost && <><th>{t("modules:fuel.unitPrice")}</th><th>{t("common:labels.totalCost")}</th></>}<th>{t("common:labels.location")}</th>
              <th>{t("modules:fuel.station")}</th><th>{t("common:labels.odometer")}</th><th>{t("modules:fuel.bill")}</th>
              {canEdit && <th>{t("common:labels.actions")}</th>}
            </tr>
          </thead>
          <tbody>
            {filtered.map((record) => {
              const isEditing = editingId === record.id && editForm;
              const editTotal = isEditing
                ? calculatedCost(editForm.quantity, editForm.unit_cost)
                : "";
              return (
                <tr key={record.id}>
                  <td><strong>{record.license_plate}</strong></td>
                  <td>{record.brand} {record.model}</td>
                  <td>{canEdit && isEditing ? <input className="input compactInput" type="date" value={editForm.refuel_date} onChange={(event) => setEditForm({ ...editForm, refuel_date: event.target.value })} /> : formatDate(record.refuel_date)}</td>
                  <td>
                    {translateType(record.fuel_type)}
                    {record.unit_review_required && <div className="muted">{t("modules:fuel.unitReview")}</div>}
                  </td>
                  <td>{canEdit && isEditing
                    ? <div><label className="muted">{quantityLabel(record.unit)}</label><input aria-label={quantityLabel(record.unit)} className="input compactInput" type="number" min="0.001" step="0.001" value={editForm.quantity} onChange={(event) => setEditForm({ ...editForm, quantity: event.target.value })} /></div>
                    : formatEnergyQuantity(record.quantity, record.unit)}
                  </td>
                  {canViewCost && <td>{canEdit && isEditing
                    ? <div><label className="muted">{unitCostLabel(record.unit)}</label><input aria-label={unitCostLabel(record.unit)} className="input compactInput" type="number" min="0" step="0.0001" value={editForm.unit_cost} onChange={(event) => setEditForm({ ...editForm, unit_cost: event.target.value })} /></div>
                    : record.unit_cost == null ? "-" : formatEnergyUnitPrice(record.unit_cost, record.unit)}
                  </td>}
                  {canViewCost && <td>{isEditing ? formatCurrency(editTotal) : record.total_cost == null ? "-" : formatCurrency(record.total_cost)}</td>}
                  <td>{canEdit && isEditing ? <input className="input compactInput" value={editForm.location} onChange={(event) => setEditForm({ ...editForm, location: event.target.value })} /> : record.location}</td>
                  <td>{canEdit && isEditing ? <input className="input compactInput" value={editForm.station_name} onChange={(event) => setEditForm({ ...editForm, station_name: event.target.value })} /> : record.station_name}</td>
                  <td>{canEdit && isEditing ? <input className="input compactInput" type="number" value={editForm.odometer_km} onChange={(event) => setEditForm({ ...editForm, odometer_km: event.target.value })} /> : formatNumber(record.odometer_km)}</td>
                  <td>{record.bill_file_path ? <button className="linkButton" type="button" onClick={() => void apiDownloadFile(record.bill_file_path!, `fuel-${record.id}-bill`)}>{t("common:actions.download")}</button> : "-"}</td>
                  {canEdit && <td>
                    <div className="actions">
                      {isEditing
                        ? <>
                          <button className="button smallButton" type="button" onClick={() => void saveEdit(record.id)}>{t("common:actions.save")}</button>
                          <button className="secondaryButton smallButton" type="button" onClick={() => { setEditingId(null); setEditForm(null); }}>{t("common:actions.cancel")}</button>
                        </>
                        : <button className="secondaryButton smallButton" type="button" onClick={() => startEdit(record)}>{t("common:actions.edit")}</button>}
                      <button className="dangerButton smallButton" type="button" onClick={() => void deleteFuel(record)}>{t("common:actions.archive")}</button>
                    </div>
                  </td>}
                </tr>
              );
            })}
            {filtered.length === 0 && <tr><td colSpan={(canViewCost ? 11 : 9) + (canEdit ? 1 : 0)} className="muted">{t("modules:fuel.empty")}</td></tr>}
          </tbody>
        </table>
      )}
    </section>
  );
}
