"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiGet, apiPut } from "@/lib/api";
import type { Vehicle, VehiclePayload } from "@/lib/types";
import { FUEL_TYPES } from "@/lib/constants";

export default function EditVehiclePage({ params }: { params: { id: string } }) {
  const router = useRouter();
  const [form, setForm] = useState<VehiclePayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<Vehicle>(`/vehicles/${params.id}`).then((vehicle) => {
      const { id, status_name, ...payload } = vehicle;
      setForm(payload);
    }).catch((err) => setError(err instanceof Error ? err.message : "Could not load vehicle"));
  }, [params.id]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!form) return;
    setError(null);
    try {
      await apiPut<Vehicle>(`/vehicles/${params.id}`, form);
      router.push("/vehicles");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update vehicle");
    }
  }

  if (!form) return <div className="card">Loading vehicle...</div>;

  return (
    <section>
      <h1>Edit vehicle</h1>
      <form onSubmit={submit} className="form card">
        {error && <div className="error">{error}</div>}
        <div className="formRow"><label>License plate</label><input className="input" value={form.license_plate} onChange={(e) => setForm({ ...form, license_plate: e.target.value })} /></div>
        <div className="formRow"><label>Brand</label><input className="input" value={form.brand} onChange={(e) => setForm({ ...form, brand: e.target.value })} /></div>
        <div className="formRow"><label>Model</label><input className="input" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} /></div>
        <div className="formRow"><label>Fuel type</label><select className="select" value={form.fuel_type} onChange={(e) => setForm({ ...form, fuel_type: e.target.value })}>{FUEL_TYPES.map((fuel) => <option key={fuel}>{fuel}</option>)}</select></div>
        <div className="formRow"><label>Location</label><input className="input" value={form.vehicle_location} onChange={(e) => setForm({ ...form, vehicle_location: e.target.value })} /></div>
        <div className="formRow"><label>Status</label><select className="select" value={form.status} onChange={(e) => setForm({ ...form, status: Number(e.target.value) })}><option value={0}>Active</option><option value={1}>In Service</option><option value={2}>Sold</option><option value={3}>Out of Use</option></select></div>
        <div className="formRow"><label>Odometer KM</label><input className="input" type="number" value={form.odometer_km ?? ""} onChange={(e) => setForm({ ...form, odometer_km: e.target.value ? Number(e.target.value) : null })} /></div>
        <button className="button" type="submit">Update vehicle</button>
      </form>
    </section>
  );
}
