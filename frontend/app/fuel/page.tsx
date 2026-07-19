"use client";

import { useEffect, useMemo, useState } from "react";
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
  const { can } = useAuth();
  const canWrite = can("fuelWrite");
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
      setError(err instanceof Error ? err.message : "Could not load fuel or charging records");
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
      setVehiclesError(err instanceof Error ? err.message : "Could not load Vehicles");
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
      name: `${vehicle.license_plate} — ${vehicle.brand} ${vehicle.model} — ${vehicle.fuel_type}`
    })),
    [vehicles]
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
      setError("Select a valid Vehicle before entering fuel or charging details.");
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
      setMessage(result.message ?? "Fuel or charging record added.");
      setForm(emptyFuelForm());
      setBillFile(null);
      setIsFuelDialogOpen(false);
      await loadFuelRecords();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add fuel or charging record");
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
      setMessage(result.message ?? "Fuel or charging record updated.");
      setEditingId(null);
      setEditForm(null);
      await loadFuelRecords();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update fuel or charging record");
    }
  }

  async function deleteFuel(record: FuelRecord) {
    if (!confirm(`Archive ${record.fuel_type === "Electric" ? "charging" : "fuel"} record for ${record.license_plate} from ${record.refuel_date}?\n\nIt will be hidden from normal views but retained for history and audit purposes.`)) return;
    setError(null);
    setMessage(null);
    try {
      const result = await apiDelete<ApiMessage>(`/fuel/${record.id}`);
      setMessage(result.message ?? "Fuel or charging record archived.");
      await loadFuelRecords();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to archive fuel or charging record");
    }
  }

  return (
    <section>
      <EntityPageHeader
        title="Fuel & Charging Records"
        description="Track fuel purchases, electric charging, energy cost, and vehicle mileage."
        actionLabel={canWrite ? "Add Fuel Record" : undefined}
        onAction={canWrite ? openFuelDialog : undefined}
      />
      {error && !isFuelDialogOpen && <div className="error spaced" role="alert">{error}</div>}
      {message && <div className="success spaced" role="status">{message}</div>}

      {canWrite && <CreateEntityDialog
        open={isFuelDialogOpen}
        title="Add Fuel Record"
        description="Record fuel or electric charging details, mileage, cost, and an optional bill."
        busy={submitting}
        onClose={closeFuelDialog}
      >
        <form onSubmit={registerFuel} className="form dialogForm">
          {error && <div className="error" role="alert">{error}</div>}
          <div className="formGrid">
            <div className="formRow span2">
              <label htmlFor="fuel-vehicle">Vehicle</label>
              <SearchableCombobox
                id="fuel-vehicle"
                options={vehicleOptions}
                value={form.vehicle_id}
                onChange={selectVehicle}
                placeholder="Search by licence plate, brand, or model"
                searchPlaceholder="Type a licence plate, brand, or model"
                emptyText="No Vehicle matches this search."
                loadingText="Loading Vehicles..."
                loading={vehiclesLoading}
                error={vehiclesError}
                required
              />
            </div>

            <div className="formRow">
              <label>{selectedUnit === "KWH" ? "Energy type" : "Fuel type"}</label>
              <div className="input" aria-label={selectedUnit === "KWH" ? "Energy type" : "Fuel type"}>
                {selectedVehicle?.fuel_type ?? "Select a Vehicle first"}
              </div>
            </div>
            <div className="formRow">
              <label htmlFor="fuel-refuel-date">Fuel / charging date</label>
              <input id="fuel-refuel-date" className="input" type="date" value={form.refuel_date} onChange={(event) => setForm({ ...form, refuel_date: event.target.value })} required />
            </div>

            {selectedVehicle && <div className="card span2">
              <div className="muted">Selected Vehicle</div>
              <strong>{selectedVehicle.license_plate}</strong>
              <div>{selectedVehicle.brand} {selectedVehicle.model}</div>
              <div>{selectedUnit === "KWH" ? "Energy type" : "Fuel type"}: {selectedVehicle.fuel_type}</div>
              <div>Current odometer: {(selectedVehicle.odometer_km ?? 0).toLocaleString()} km</div>
              <div>Location: {selectedVehicle.vehicle_location}</div>
            </div>}

            <div className="formRow">
              <label htmlFor="fuel-quantity">{selectedUnit ? quantityLabel(selectedUnit) : "Quantity"}</label>
              <input
                id="fuel-quantity"
                className="input"
                type="number"
                min="0.001"
                step="0.001"
                value={form.quantity}
                onChange={(event) => setForm({ ...form, quantity: event.target.value })}
                placeholder={selectedUnit ? undefined : "Select a Vehicle first"}
                disabled={!selectedVehicle}
                required
              />
            </div>
            <div className="formRow">
              <label htmlFor="fuel-unit-cost">{selectedUnit ? unitCostLabel(selectedUnit) : "Unit cost"}</label>
              <input
                id="fuel-unit-cost"
                className="input"
                type="number"
                min="0"
                step="0.0001"
                value={form.unit_cost}
                onChange={(event) => setForm({ ...form, unit_cost: event.target.value })}
                placeholder={selectedUnit ? undefined : "Select a Vehicle first"}
                disabled={!selectedVehicle}
                required
              />
            </div>
            <div className="formRow">
              <label htmlFor="fuel-total-cost">Calculated total</label>
              <input
                id="fuel-total-cost"
                className="input"
                value={calculatedTotal}
                placeholder={selectedUnit ? calculationDescription(selectedUnit) : "Select a Vehicle first"}
                readOnly
              />
            </div>
            <div className="formRow">
              <label htmlFor="fuel-odometer">Odometer KM</label>
              <input
                id="fuel-odometer"
                className="input"
                type="number"
                min={selectedVehicle?.odometer_km ?? 0}
                value={form.odometer_km}
                onChange={(event) => setForm({ ...form, odometer_km: event.target.value })}
                placeholder={selectedVehicle ? `Current: ${(selectedVehicle.odometer_km ?? 0).toLocaleString()} km` : "Select a Vehicle first"}
                disabled={!selectedVehicle}
              />
            </div>
            <div className="formRow">
              <label htmlFor="fuel-location">Location</label>
              <input id="fuel-location" className="input" value={form.location} onChange={(event) => setForm({ ...form, location: event.target.value })} disabled={!selectedVehicle} />
            </div>
            <div className="formRow">
              <label htmlFor="fuel-station">{selectedUnit ? stationLabel(selectedUnit) : "Station / provider"}</label>
              <input id="fuel-station" className="input" value={form.station_name} onChange={(event) => setForm({ ...form, station_name: event.target.value })} disabled={!selectedVehicle} />
            </div>
            <div className="formRow span2">
              <label htmlFor="fuel-bill-file">Bill file optional</label>
              <input id="fuel-bill-file" className="input" type="file" onChange={(event) => setBillFile(event.target.files?.[0] ?? null)} disabled={!selectedVehicle} />
            </div>
          </div>
          <div className="actions dialogActions">
            <button className="secondaryButton" type="button" onClick={closeFuelDialog} disabled={submitting}>Cancel</button>
            <button className="button" type="submit" disabled={submitting || !selectedVehicle}>{submitting ? "Saving..." : "Save Fuel Record"}</button>
          </div>
        </form>
      </CreateEntityDialog>}

      <div className="card filtersGrid spaced">
        <input className="input" value={filters.search} onChange={(event) => setFilters({ ...filters, search: event.target.value })} placeholder="Search plate, vehicle, location, station or provider" />
        <select className="select" value={filters.fuel_type} onChange={(event) => setFilters({ ...filters, fuel_type: event.target.value })}>
          <option value="">All fuel / energy types</option>
          {FUEL_TYPES.map((fuel) => <option key={fuel}>{fuel}</option>)}
        </select>
        <select className="select" value={filters.location} onChange={(event) => setFilters({ ...filters, location: event.target.value })}>
          <option value="">All locations</option>
          {locations.map((location) => <option key={location}>{location}</option>)}
        </select>
        <input className="input" value={filters.station} onChange={(event) => setFilters({ ...filters, station: event.target.value })} placeholder="Station or provider" />
        <input className="input" type="date" value={filters.from_date} onChange={(event) => setFilters({ ...filters, from_date: event.target.value })} />
        <input className="input" type="date" value={filters.to_date} onChange={(event) => setFilters({ ...filters, to_date: event.target.value })} />
      </div>

      {loading ? <div className="card">Loading fuel and charging records...</div> : (
        <table className="table">
          <thead>
            <tr>
              <th>Plate</th><th>Vehicle</th><th>Date</th><th>Fuel / Energy Type</th>
              <th>Quantity</th><th>Unit Price</th><th>Total Cost</th><th>Location</th>
              <th>Station / Provider</th><th>Odometer</th><th>Bill</th>
              {canWrite && <th>Actions</th>}
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
                  <td>{canWrite && isEditing ? <input className="input compactInput" type="date" value={editForm.refuel_date} onChange={(event) => setEditForm({ ...editForm, refuel_date: event.target.value })} /> : record.refuel_date}</td>
                  <td>
                    {record.fuel_type}
                    {record.unit_review_required && <div className="muted">Unit review required</div>}
                  </td>
                  <td>{canWrite && isEditing
                    ? <div><label className="muted">{quantityLabel(record.unit)}</label><input aria-label={quantityLabel(record.unit)} className="input compactInput" type="number" min="0.001" step="0.001" value={editForm.quantity} onChange={(event) => setEditForm({ ...editForm, quantity: event.target.value })} /></div>
                    : formatEnergyQuantity(record.quantity, record.unit)}
                  </td>
                  <td>{canWrite && isEditing
                    ? <div><label className="muted">{unitCostLabel(record.unit)}</label><input aria-label={unitCostLabel(record.unit)} className="input compactInput" type="number" min="0" step="0.0001" value={editForm.unit_cost} onChange={(event) => setEditForm({ ...editForm, unit_cost: event.target.value })} /></div>
                    : formatEnergyUnitPrice(record.unit_cost, record.unit)}
                  </td>
                  <td>{isEditing ? editTotal : Number(record.total_cost).toFixed(2)}</td>
                  <td>{canWrite && isEditing ? <input className="input compactInput" value={editForm.location} onChange={(event) => setEditForm({ ...editForm, location: event.target.value })} /> : record.location}</td>
                  <td>{canWrite && isEditing ? <input className="input compactInput" value={editForm.station_name} onChange={(event) => setEditForm({ ...editForm, station_name: event.target.value })} /> : record.station_name}</td>
                  <td>{canWrite && isEditing ? <input className="input compactInput" type="number" value={editForm.odometer_km} onChange={(event) => setEditForm({ ...editForm, odometer_km: event.target.value })} /> : record.odometer_km}</td>
                  <td>{record.bill_file_path ? <button className="linkButton" type="button" onClick={() => void apiDownloadFile(record.bill_file_path!, `fuel-${record.id}-bill`)}>Download</button> : "-"}</td>
                  {canWrite && <td>
                    <div className="actions">
                      {isEditing
                        ? <>
                          <button className="button smallButton" type="button" onClick={() => void saveEdit(record.id)}>Save</button>
                          <button className="secondaryButton smallButton" type="button" onClick={() => { setEditingId(null); setEditForm(null); }}>Cancel</button>
                        </>
                        : <button className="secondaryButton smallButton" type="button" onClick={() => startEdit(record)}>Edit</button>}
                      <button className="dangerButton smallButton" type="button" onClick={() => void deleteFuel(record)}>Archive</button>
                    </div>
                  </td>}
                </tr>
              );
            })}
            {filtered.length === 0 && <tr><td colSpan={canWrite ? 12 : 11} className="muted">No fuel or charging records match your filters.</td></tr>}
          </tbody>
        </table>
      )}
    </section>
  );
}
