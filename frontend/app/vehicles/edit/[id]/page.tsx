"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { VehicleForm, vehicleToPayload } from "@/components/vehicles/VehicleForm";
import { apiGet, apiPut } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Vehicle, VehiclePayload } from "@/lib/types";

export default function EditVehiclePage({ params }: { params: { id: string } }) {
  const router = useRouter();
  const { can } = useAuth();
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    apiGet<Vehicle>(`/vehicles/${params.id}`)
      .then(setVehicle)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load vehicle"));
  }, [params.id]);

  async function updateVehicle(payload: VehiclePayload) {
    setError(null);
    setSubmitting(true);
    try {
      await apiPut<Vehicle>(`/vehicles/${params.id}`, payload);
      router.push("/vehicles");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update vehicle");
    } finally {
      setSubmitting(false);
    }
  }

  if (!can("vehiclesWrite")) {
    return <div className="error">You do not have permission to edit vehicles.</div>;
  }

  if (!vehicle) return error ? <div className="error">{error}</div> : <div className="card">Loading vehicle...</div>;

  return (
    <section>
      <h1>Edit Vehicle</h1>
      <p className="muted">Update the vehicle identification, technical, and fleet information.</p>
      <VehicleForm
        mode="edit"
        initialValues={vehicleToPayload(vehicle)}
        error={error}
        submitting={submitting}
        onSubmit={updateVehicle}
        onCancel={() => router.push("/vehicles")}
        className="card spaced"
      />
    </section>
  );
}
