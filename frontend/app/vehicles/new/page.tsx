"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiPost } from "@/lib/api";
import type { Vehicle, VehiclePayload } from "@/lib/types";
import { FUEL_TYPES } from "@/lib/constants";

const initial: VehiclePayload = {
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

export default function NewVehiclePage() {
  const router = useRouter();
  const [form, setForm] = useState<VehiclePayload>(initial);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await apiPost<Vehicle>("/vehicles", form);
      router.push("/vehicles");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create vehicle");
    }
  }

  return (
    <section>
      <h1>Add vehicle</h1>
      <form onSubmit={submit} className="form card">
        {error && <div className="error">{error}</div>}
        <div className="formRow"><label>License plate</label><input className="input" value={form.license_plate} onChange={(e) => setForm({ ...form, license_plate: e.target.value })} placeholder="01-123-AB" /></div>
        <div className="formRow"><label>Brand</label><input className="input" value={form.brand} onChange={(e) => setForm({ ...form, brand: e.target.value })} /></div>
        <div className="formRow"><label>Model</label><input className="input" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} /></div>
        <div className="formRow"><label>Fuel type</label><select className="select" value={form.fuel_type} onChange={(e) => setForm({ ...form, fuel_type: e.target.value })}>{FUEL_TYPES.map((fuel) => <option key={fuel}>{fuel}</option>)}</select></div>
        <div className="formRow"><label>Location</label><input className="input" value={form.vehicle_location} onChange={(e) => setForm({ ...form, vehicle_location: e.target.value })} /></div>
        <div className="formRow"><label>Year</label><input className="input" type="number" value={form.year ?? ""} onChange={(e) => setForm({ ...form, year: e.target.value ? Number(e.target.value) : null })} /></div>
        <div className="formRow"><label>VIN</label><input className="input" value={form.vin_number ?? ""} onChange={(e) => setForm({ ...form, vin_number: e.target.value || null })} /></div>
        <div className="formRow"><label>Engine CC</label><input className="input" type="number" value={form.engine_cc ?? ""} onChange={(e) => setForm({ ...form, engine_cc: e.target.value ? Number(e.target.value) : null })} /></div>
        <div className="formRow"><label>Odometer KM</label><input className="input" type="number" value={form.odometer_km ?? ""} onChange={(e) => setForm({ ...form, odometer_km: e.target.value ? Number(e.target.value) : null })} /></div>
        <button className="button" type="submit">Save vehicle</button>
      </form>
    </section>
  );
}
