"use client";

import { useCallback, useEffect, useId, useState } from "react";
import { SearchableCombobox } from "@/components/ui/SearchableCombobox";
import { FUEL_TYPES, VEHICLE_STATUSES } from "@/lib/constants";
import { vehicleCatalogApi, vehicleRegistrationApi } from "@/lib/api";
import { formatLicensePlateInput, validateLicensePlateInput } from "@/lib/licensePlates";
import type {
  RegistrationCountryCode, RegistrationCountryOption, Vehicle, VehicleBrand,
  VehicleFormInitialValues, VehicleFormValues, VehicleModel, VehiclePayload
} from "@/lib/types";

type VehicleFormProps = {
  mode?: "create" | "edit";
  initialValues?: VehicleFormInitialValues;
  error?: string | null;
  submitting: boolean;
  onSubmit: (payload: VehiclePayload) => Promise<void> | void;
  onCancel?: () => void;
  className?: string;
};

const initialVehicleForm: VehicleFormValues = {
  brand_id: null,
  model_id: null,
  fuel_type: "Diesel",
  vehicle_location: "",
  registration_country: null,
  license_plate: "",
  year: null,
  vin_number: null,
  engine_cc: null,
  odometer_km: null,
  status: 0
};

export function vehicleToPayload(vehicle: Vehicle): VehicleFormInitialValues {
  return {
    brand_id: vehicle.brand_id,
    model_id: vehicle.model_id,
    brand_name: vehicle.brand,
    model_name: vehicle.model,
    fuel_type: vehicle.fuel_type,
    vehicle_location: vehicle.vehicle_location,
    registration_country: vehicle.registration_country,
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
  const [form, setForm] = useState<VehicleFormValues>(() => {
    if (!initialValues) return { ...initialVehicleForm };
    return {
      brand_id: initialValues.brand_id,
      model_id: initialValues.model_id,
      fuel_type: initialValues.fuel_type,
      vehicle_location: initialValues.vehicle_location,
      registration_country: initialValues.registration_country,
      license_plate: initialValues.license_plate,
      year: initialValues.year,
      vin_number: initialValues.vin_number,
      engine_cc: initialValues.engine_cc,
      odometer_km: initialValues.odometer_km,
      status: initialValues.status
    };
  });
  const [fallbackLabels, setFallbackLabels] = useState({
    brand: initialValues?.brand_name,
    model: initialValues?.model_name
  });
  const [brands, setBrands] = useState<VehicleBrand[]>([]);
  const [models, setModels] = useState<VehicleModel[]>([]);
  const [loadingBrands, setLoadingBrands] = useState(true);
  const [loadingModels, setLoadingModels] = useState(Boolean(initialValues?.brand_id));
  const [brandError, setBrandError] = useState<string | null>(null);
  const [modelError, setModelError] = useState<string | null>(null);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const [countries, setCountries] = useState<RegistrationCountryOption[]>([]);
  const [countryError, setCountryError] = useState<string | null>(null);
  const [plateError, setPlateError] = useState<string | null>(null);

  const loadBrands = useCallback((force = false) => {
    setLoadingBrands(true);
    setBrandError(null);
    vehicleCatalogApi.getBrands(force)
      .then(setBrands)
      .catch(() => setBrandError("Vehicle brands could not be loaded."))
      .finally(() => setLoadingBrands(false));
  }, []);

  useEffect(() => {
    loadBrands();
  }, [loadBrands]);

  useEffect(() => {
    vehicleRegistrationApi.getCountries()
      .then(setCountries)
      .catch(() => setCountryError("Registration countries could not be loaded."));
  }, []);

  useEffect(() => {
    let active = true;
    if (form.brand_id === null) {
      setModels([]);
      setLoadingModels(false);
      setModelError(null);
      return () => { active = false; };
    }
    setLoadingModels(true);
    setModelError(null);
    vehicleCatalogApi.getModelsByBrand(form.brand_id)
      .then((items) => {
        if (active) setModels(items);
      })
      .catch(() => {
        if (active) setModelError("Vehicle models could not be loaded for the selected brand.");
      })
      .finally(() => {
        if (active) setLoadingModels(false);
      });
    return () => { active = false; };
  }, [form.brand_id]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (form.brand_id === null) {
      setSelectionError("Select a vehicle brand.");
      return;
    }
    if (form.model_id === null) {
      setSelectionError("Select a vehicle model.");
      return;
    }
    if (form.registration_country === null) {
      setSelectionError("Select a registration country.");
      return;
    }
    const validationMessage = validateLicensePlateInput(form.registration_country, form.license_plate);
    if (validationMessage) {
      setPlateError(validationMessage);
      return;
    }
    setPlateError(null);
    setSelectionError(null);
    await onSubmit({
      ...form,
      brand_id: form.brand_id,
      model_id: form.model_id,
      registration_country: form.registration_country
    });
  }

  const selectedCountry = countries.find((country) => country.code === form.registration_country);

  return (
    <form onSubmit={submit} className={`form fullWidthForm ${className}`.trim()}>
      {(error || selectionError || countryError) && <div className="error" role="alert">{error || selectionError || countryError}</div>}
      <div className="formGrid">
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-registration-country`}>Registration country</label>
          <select
            id={`${fieldPrefix}-registration-country`}
            className="select"
            value={form.registration_country ?? ""}
            onChange={(event) => {
              const registration_country = event.target.value as RegistrationCountryCode | "";
              setPlateError(null);
              setSelectionError(null);
              setForm((current) => ({
                ...current,
                registration_country: registration_country || null,
                license_plate: ""
              }));
            }}
            required
          >
            <option value="">Select country</option>
            {countries.map((country) => <option key={country.code} value={country.code}>{country.name}</option>)}
          </select>
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-license-plate`}>Licence plate</label>
          <input
            id={`${fieldPrefix}-license-plate`}
            className="input"
            value={form.license_plate}
            onChange={(event) => {
              if (!form.registration_country) return;
              setPlateError(null);
              setForm({
                ...form,
                license_plate: formatLicensePlateInput(form.registration_country, event.target.value)
              });
            }}
            onBlur={() => {
              if (form.registration_country && form.license_plate) {
                setPlateError(validateLicensePlateInput(form.registration_country, form.license_plate));
              }
            }}
            placeholder={selectedCountry?.placeholder ?? "Select a registration country first"}
            aria-describedby={`${fieldPrefix}-license-plate-help`}
            aria-invalid={Boolean(plateError)}
            disabled={!form.registration_country}
            inputMode="text"
            autoComplete="off"
            maxLength={9}
            required
          />
          <span id={`${fieldPrefix}-license-plate-help`} className={plateError ? "errorText" : "muted"} aria-live="polite">
            {plateError ?? selectedCountry?.helper_text.join(" · ") ?? "Select a registration country before entering the licence plate."}
          </span>
          {mode === "edit" && !initialValues?.registration_country && (
            <span className="errorText" role="alert">Registration country must be selected before this Vehicle can be updated.</span>
          )}
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-brand`}>Brand</label>
          <SearchableCombobox
            id={`${fieldPrefix}-brand`}
            options={brands}
            value={form.brand_id}
            selectedLabel={fallbackLabels.brand}
            onChange={(brandId) => {
              setFallbackLabels({ brand: undefined, model: undefined });
              setSelectionError(null);
              setForm((current) => ({ ...current, brand_id: brandId, model_id: null }));
            }}
            placeholder={loadingBrands ? "Loading brands..." : "Select vehicle brand"}
            searchPlaceholder="Search brands..."
            emptyText="No vehicle brands found."
            loadingText="Loading brands..."
            loading={loadingBrands}
            error={brandError}
            required
          />
          {brandError && <button className="linkButton retryButton" type="button" onClick={() => loadBrands(true)}>Retry loading brands</button>}
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-model`}>Model</label>
          <SearchableCombobox
            id={`${fieldPrefix}-model`}
            options={models}
            value={form.model_id}
            selectedLabel={fallbackLabels.model}
            onChange={(modelId) => {
              setFallbackLabels((current) => ({ ...current, model: undefined }));
              setSelectionError(null);
              setForm((current) => ({ ...current, model_id: modelId }));
            }}
            placeholder={form.brand_id === null ? "Select a brand first" : "Select vehicle model"}
            searchPlaceholder="Search models..."
            emptyText="No models are available for this brand."
            loadingText="Loading models..."
            loading={loadingModels}
            disabled={form.brand_id === null}
            error={modelError}
            required
          />
          {modelError && form.brand_id !== null && (
            <button
              className="linkButton retryButton"
              type="button"
              onClick={() => {
                if (form.brand_id === null) return;
                setLoadingModels(true);
                setModelError(null);
                vehicleCatalogApi.getModelsByBrand(form.brand_id, true)
                  .then(setModels)
                  .catch(() => setModelError("Vehicle models could not be loaded for the selected brand."))
                  .finally(() => setLoadingModels(false));
              }}
            >
              Retry loading models
            </button>
          )}
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
        <button className="button" type="submit" disabled={submitting || loadingBrands || loadingModels}>
          {submitting ? (mode === "edit" ? "Updating..." : "Creating...") : (mode === "edit" ? "Update Vehicle" : "Create Vehicle")}
        </button>
      </div>
    </form>
  );
}
