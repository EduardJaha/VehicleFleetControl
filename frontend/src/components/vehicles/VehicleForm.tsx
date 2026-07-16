"use client";

import { useId, useState } from "react";
import { FUEL_TYPES, VEHICLE_STATUSES } from "@/lib/constants";
import type { Vehicle, VehiclePayload } from "@/lib/types";

type VehicleFormProps = {
  mode?: "create" | "edit";
  initialValues?: VehiclePayload;
  error?: string | null;
  submitting: boolean;
  onSubmit: (payload: VehiclePayload) => Promise<void> | void;
  onCancel?: () => void;
  className?: string;
};

const initialVehicleForm: VehiclePayload = {
  brand: "",
  model: "",
  fuel_type: "Diesel",
  vehicle_location: "",
  license_plate: "",
  year: null,
  vin_number: null,
  engine_cc: null,
  odometer_km: null,
  status: 0
};

export function vehicleToPayload(vehicle: Vehicle): VehiclePayload {
  return {
    brand: vehicle.brand,
    model: vehicle.model,
    fuel_type: vehicle.fuel_type,
    vehicle_location: vehicle.vehicle_location,
    license_plate: vehicle.license_plate,
    year: vehicle.year ?? null,
    vin_number: vehicle.vin_number ?? null,
    engine_cc: vehicle.engine_cc ?? null,
    odometer_km: vehicle.odometer_km ?? null,
    status: vehicle.status
  };
}

export function VehicleForm({ mode = "create", initialValues, error, submitting, onSubmit, onCancel, className = "" }: VehicleFormProps) {
  const fieldPrefix = useId();
  const [form, setForm] = useState<VehiclePayload>(() => ({ ...(initialValues ?? initialVehicleForm) }));

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    await onSubmit(form);
  }

  return (
    <form onSubmit={submit} className={`form fullWidthForm ${className}`.trim()}>
      {error && <div className="error" role="alert">{error}</div>}
      <div className="formGrid">
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-license-plate`}>License plate</label>
          <input id={`${fieldPrefix}-license-plate`} className="input" value={form.license_plate} onChange={(event) => setForm({ ...form, license_plate: event.target.value })} placeholder="01-123-AB" required />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-brand`}>Brand</label>
          <input id={`${fieldPrefix}-brand`} className="input" value={form.brand} onChange={(event) => setForm({ ...form, brand: event.target.value })} required />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-model`}>Model</label>
          <input id={`${fieldPrefix}-model`} className="input" value={form.model} onChange={(event) => setForm({ ...form, model: event.target.value })} required />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-fuel-type`}>Fuel type</label>
          <select id={`${fieldPrefix}-fuel-type`} className="select" value={form.fuel_type} onChange={(event) => setForm({ ...form, fuel_type: event.target.value })} required>
            {FUEL_TYPES.map((fuel) => <option key={fuel}>{fuel}</option>)}
          </select>
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-location`}>Location</label>
          <input id={`${fieldPrefix}-location`} className="input" value={form.vehicle_location} onChange={(event) => setForm({ ...form, vehicle_location: event.target.value })} required />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-year`}>Year</label>
          <input id={`${fieldPrefix}-year`} className="input" type="number" min="1900" max="2100" value={form.year ?? ""} onChange={(event) => setForm({ ...form, year: event.target.value ? Number(event.target.value) : null })} />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-vin`}>VIN</label>
          <input id={`${fieldPrefix}-vin`} className="input" maxLength={50} value={form.vin_number ?? ""} onChange={(event) => setForm({ ...form, vin_number: event.target.value || null })} />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-engine-cc`}>Engine CC</label>
          <input id={`${fieldPrefix}-engine-cc`} className="input" type="number" min="50" max="10000" value={form.engine_cc ?? ""} onChange={(event) => setForm({ ...form, engine_cc: event.target.value ? Number(event.target.value) : null })} />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-odometer`}>Odometer KM</label>
          <input id={`${fieldPrefix}-odometer`} className="input" type="number" min="0" max="2000000" value={form.odometer_km ?? ""} onChange={(event) => setForm({ ...form, odometer_km: event.target.value ? Number(event.target.value) : null })} />
        </div>
        {mode === "edit" && <div className="formRow">
          <label htmlFor={`${fieldPrefix}-status`}>Status</label>
          <select id={`${fieldPrefix}-status`} className="select" value={form.status} onChange={(event) => setForm({ ...form, status: Number(event.target.value) })} required>
            {VEHICLE_STATUSES.map((status) => <option key={status.value} value={status.value}>{status.label}</option>)}
          </select>
        </div>}
      </div>
      <div className="actions dialogActions">
        {onCancel && <button className="secondaryButton" type="button" onClick={onCancel} disabled={submitting}>Cancel</button>}
        <button className="button" type="submit" disabled={submitting}>
          {submitting ? (mode === "edit" ? "Updating..." : "Creating...") : (mode === "edit" ? "Update Vehicle" : "Create Vehicle")}
        </button>
      </div>
    </form>
  );
}
