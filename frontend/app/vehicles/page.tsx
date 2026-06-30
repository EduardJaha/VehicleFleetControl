"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { apiDelete, apiGet, buildQuery } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { ApiMessage, Vehicle } from "@/lib/types";
import { FUEL_TYPES, VEHICLE_STATUS_LABELS, VEHICLE_STATUSES } from "@/lib/constants";

export default function VehiclesPage() {
  const { can } = useAuth();
  const canWrite = can("vehiclesWrite");
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [filters, setFilters] = useState({ search: "", fuel: "", location: "", status: "" });

  async function loadVehicles(status = filters.status) {
    setLoading(true);
    setError(null);
    try {
      const data = await apiGet<Vehicle[]>(`/vehicles${buildQuery({ status })}`);
      setVehicles(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load vehicles");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadVehicles("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const locations = useMemo(() => Array.from(new Set(vehicles.map((v) => v.vehicle_location).filter(Boolean))).sort(), [vehicles]);

  const filtered = useMemo(() => {
    const text = filters.search.trim().toLowerCase();
    return vehicles.filter((vehicle) => {
      const matchesText = !text || [vehicle.license_plate, vehicle.brand, vehicle.model, vehicle.vehicle_location, vehicle.vin_number ?? ""].some((value) => value.toLowerCase().includes(text));
      const matchesFuel = !filters.fuel || vehicle.fuel_type === filters.fuel;
      const matchesLocation = !filters.location || vehicle.vehicle_location === filters.location;
      return matchesText && matchesFuel && matchesLocation;
    });
  }, [vehicles, filters]);

  async function deleteVehicle(vehicle: Vehicle) {
    if (!confirm(`Delete vehicle ${vehicle.license_plate}? This cannot be undone.`)) return;
    setError(null);
    setMessage(null);
    try {
      const result = await apiDelete<ApiMessage>(`/vehicles/${vehicle.id}`);
      setMessage(result.message ?? "Vehicle deleted.");
      await loadVehicles();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete vehicle");
    }
  }

  return (
    <section>
      <div className="header">
        <div>
          <h1>Vehicles</h1>
          <p className="muted">Vehicle registry, search, filtering, edit, and delete actions.</p>
        </div>
        {canWrite && <Link href="/vehicles/new" className="button">Add vehicle</Link>}
      </div>

      <div className="card filtersGrid">
        <input className="input" value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} placeholder="Search plate, brand, model, VIN, location" />
        <select className="select" value={filters.status} onChange={(e) => { const status = e.target.value; setFilters((current) => ({ ...current, status })); void loadVehicles(status); }}>
          <option value="">All statuses</option>
          {VEHICLE_STATUSES.map((status) => <option key={status.value} value={status.value}>{status.label}</option>)}
        </select>
        <select className="select" value={filters.fuel} onChange={(e) => setFilters({ ...filters, fuel: e.target.value })}>
          <option value="">All fuel types</option>
          {FUEL_TYPES.map((fuel) => <option key={fuel}>{fuel}</option>)}
        </select>
        <select className="select" value={filters.location} onChange={(e) => setFilters({ ...filters, location: e.target.value })}>
          <option value="">All locations</option>
          {locations.map((location) => <option key={location}>{location}</option>)}
        </select>
      </div>

      {error && <div className="error spaced">{error}</div>}
      {message && <div className="success spaced">{message}</div>}
      {loading ? <div className="card">Loading vehicles...</div> : (
        <table className="table">
          <thead>
            <tr>
              <th>Plate</th><th>Brand</th><th>Model</th><th>Fuel</th><th>Location</th><th>Odometer</th><th>Status</th>{canWrite && <th>Actions</th>}
            </tr>
          </thead>
          <tbody>
            {filtered.map((vehicle) => (
              <tr key={vehicle.id}>
                <td><strong>{vehicle.license_plate}</strong></td>
                <td>{vehicle.brand}</td>
                <td>{vehicle.model}</td>
                <td>{vehicle.fuel_type}</td>
                <td>{vehicle.vehicle_location}</td>
                <td>{vehicle.odometer_km ?? "-"}</td>
                <td><span className="badge">{VEHICLE_STATUS_LABELS[vehicle.status] ?? vehicle.status_name}</span></td>
                {canWrite && (
                  <td>
                    <div className="actions">
                      <Link className="secondaryButton smallButton" href={`/vehicles/edit/${vehicle.id}`}>Edit</Link>
                      <button className="dangerButton smallButton" type="button" onClick={() => void deleteVehicle(vehicle)}>Delete</button>
                    </div>
                  </td>
                )}
              </tr>
            ))}
            {filtered.length === 0 && <tr><td colSpan={canWrite ? 8 : 7} className="muted">No vehicles match your filters.</td></tr>}
          </tbody>
        </table>
      )}
    </section>
  );
}
