"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useRouter } from "next/navigation";
import { VehicleForm } from "@/components/vehicles/VehicleForm";
import { apiPost } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Vehicle, VehiclePayload } from "@/lib/types";

export default function NewVehiclePage() {
  const { t } = useTranslation("modules");
  const router = useRouter();
  const { can } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function createVehicle(payload: VehiclePayload) {
    setError(null);
    setSubmitting(true);
    try {
      await apiPost<Vehicle>("/vehicles", payload);
      router.push("/vehicles");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("vehicles.createError"));
    } finally {
      setSubmitting(false);
    }
  }

  if (!can("vehiclesWrite")) {
    return <div className="error">{t("vehicles.accessCreate")}</div>;
  }

  return (
    <section>
      <h1>{t("vehicles.add")}</h1>
      <p className="muted">{t("vehicles.formDescription")}</p>
      <VehicleForm
        error={error}
        submitting={submitting}
        onSubmit={createVehicle}
        onCancel={() => router.push("/vehicles")}
        className="card spaced"
      />
    </section>
  );
}
