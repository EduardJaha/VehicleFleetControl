"use client";

import { useCallback, useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { SearchableCombobox } from "@/components/ui/SearchableCombobox";
import { DEPRECIATION_METHODS, FUEL_TYPES, OWNERSHIP_TYPES, VEHICLE_STATUSES } from "@/lib/constants";
import { vehicleCatalogApi, vehicleRegistrationApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";
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
  vehicle_category: null,
  registration_country: null,
  license_plate: "",
  year: null,
  vin_number: null,
  engine_cc: null,
  odometer_km: null,
  acquisition_date: null,
  purchase_price: null,
  supplier_id: null,
  ownership_type: "Owned",
  lease_start: null,
  lease_end: null,
  monthly_lease_payment: null,
  warranty_expiry: null,
  expected_service_years: null,
  expected_service_km: null,
  depreciation_method: "Straight Line",
  residual_value: null,
  sale_date: null,
  sale_price: null,
  disposal_reason: null,
  fuel_tank_capacity_l: null,
  battery_capacity_kwh: null,
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
    vehicle_category: vehicle.vehicle_category ?? null,
    registration_country: vehicle.registration_country,
    license_plate: vehicle.license_plate,
    year: vehicle.year ?? null,
    vin_number: vehicle.vin_number ?? null,
    engine_cc: vehicle.engine_cc ?? null,
    odometer_km: vehicle.odometer_km ?? null,
    acquisition_date: vehicle.acquisition_date ?? null,
    purchase_price: vehicle.purchase_price ?? null,
    supplier_id: vehicle.supplier_id ?? null,
    ownership_type: vehicle.ownership_type ?? "Owned",
    lease_start: vehicle.lease_start ?? null,
    lease_end: vehicle.lease_end ?? null,
    monthly_lease_payment: vehicle.monthly_lease_payment ?? null,
    warranty_expiry: vehicle.warranty_expiry ?? null,
    expected_service_years: vehicle.expected_service_years ?? null,
    expected_service_km: vehicle.expected_service_km ?? null,
    depreciation_method: vehicle.depreciation_method ?? "Straight Line",
    residual_value: vehicle.residual_value ?? null,
    sale_date: vehicle.sale_date ?? null,
    sale_price: vehicle.sale_price ?? null,
    disposal_reason: vehicle.disposal_reason ?? null,
    fuel_tank_capacity_l: vehicle.fuel_tank_capacity_l ?? null,
    battery_capacity_kwh: vehicle.battery_capacity_kwh ?? null,
    status: vehicle.status
  };
}

export function VehicleForm({ mode = "create", initialValues, error, submitting, onSubmit, onCancel, className = "" }: VehicleFormProps) {
  const { t, i18n } = useTranslation(["common", "modules"]);
  const { can } = useAuth();
  const canManageCatalog = can("settings.manage");
  const fieldPrefix = useId();
  const [form, setForm] = useState<VehicleFormValues>(() => {
    if (!initialValues) return { ...initialVehicleForm };
    return {
      brand_id: initialValues.brand_id,
      model_id: initialValues.model_id,
      fuel_type: initialValues.fuel_type,
      vehicle_location: initialValues.vehicle_location,
      vehicle_category: initialValues.vehicle_category ?? null,
      registration_country: initialValues.registration_country,
      license_plate: initialValues.license_plate,
      year: initialValues.year,
      vin_number: initialValues.vin_number,
      engine_cc: initialValues.engine_cc,
      odometer_km: initialValues.odometer_km,
      acquisition_date: initialValues.acquisition_date,
      purchase_price: initialValues.purchase_price,
      supplier_id: initialValues.supplier_id,
      ownership_type: initialValues.ownership_type,
      lease_start: initialValues.lease_start,
      lease_end: initialValues.lease_end,
      monthly_lease_payment: initialValues.monthly_lease_payment,
      warranty_expiry: initialValues.warranty_expiry,
      expected_service_years: initialValues.expected_service_years,
      expected_service_km: initialValues.expected_service_km,
      depreciation_method: initialValues.depreciation_method,
      residual_value: initialValues.residual_value,
      sale_date: initialValues.sale_date,
      sale_price: initialValues.sale_price,
      disposal_reason: initialValues.disposal_reason,
      fuel_tank_capacity_l: initialValues.fuel_tank_capacity_l,
      battery_capacity_kwh: initialValues.battery_capacity_kwh,
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
  const [newBrandName, setNewBrandName] = useState("");
  const [newModelName, setNewModelName] = useState("");
  const [addingBrand, setAddingBrand] = useState(false);
  const [addingModel, setAddingModel] = useState(false);
  const [savingCatalog, setSavingCatalog] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const [countries, setCountries] = useState<RegistrationCountryOption[]>([]);
  const [countryError, setCountryError] = useState<string | null>(null);
  const [plateError, setPlateError] = useState<string | null>(null);

  const loadBrands = useCallback((force = false) => {
    setLoadingBrands(true);
    setBrandError(null);
    vehicleCatalogApi.getBrands(force)
      .then(setBrands)
      .catch(() => setBrandError(t("modules:vehicles.brandLoadError")))
      .finally(() => setLoadingBrands(false));
  }, [t]);

  useEffect(() => {
    loadBrands(true);
  }, [loadBrands]);

  useEffect(() => {
    vehicleRegistrationApi.getCountries()
      .then(setCountries)
      .catch(() => setCountryError(t("modules:vehicles.countryLoadError")));
  }, [i18n.language, t]);

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
    vehicleCatalogApi.getModelsByBrand(form.brand_id, true)
      .then((items) => {
        if (active) setModels(items);
      })
      .catch(() => {
        if (active) setModelError(t("modules:vehicles.modelLoadError"));
      })
      .finally(() => {
        if (active) setLoadingModels(false);
      });
    return () => { active = false; };
  }, [form.brand_id]);

  async function saveBrand() {
    const name = newBrandName.trim();
    if (!name || savingCatalog) return;
    setSavingCatalog(true);
    setCatalogError(null);
    try {
      const brand = await vehicleCatalogApi.createBrand(name);
      setBrands((items) => [...items, brand].sort((a, b) => a.name.localeCompare(b.name)));
      setForm((current) => ({ ...current, brand_id: brand.id, model_id: null }));
      setFallbackLabels({ brand: undefined, model: undefined });
      setNewBrandName("");
      setAddingBrand(false);
      setSelectionError(null);
    } catch (err) {
      setCatalogError(err instanceof Error ? err.message : t("modules:vehicles.brandCreateError"));
    } finally {
      setSavingCatalog(false);
    }
  }

  async function saveModel() {
    const name = newModelName.trim();
    if (!name || form.brand_id === null || savingCatalog) return;
    setSavingCatalog(true);
    setCatalogError(null);
    try {
      const model = await vehicleCatalogApi.createModel(form.brand_id, name);
      setModels((items) => [...items, model].sort((a, b) => a.name.localeCompare(b.name)));
      setForm((current) => ({ ...current, model_id: model.id }));
      setFallbackLabels((current) => ({ ...current, model: undefined }));
      setNewModelName("");
      setAddingModel(false);
      setSelectionError(null);
    } catch (err) {
      setCatalogError(err instanceof Error ? err.message : t("modules:vehicles.modelCreateError"));
    } finally {
      setSavingCatalog(false);
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (form.brand_id === null) {
      setSelectionError(t("modules:vehicles.selectBrandRequired"));
      return;
    }
    if (form.model_id === null) {
      setSelectionError(t("modules:vehicles.selectModelRequired"));
      return;
    }
    if (form.registration_country === null) {
      setSelectionError(t("modules:vehicles.selectCountryRequired"));
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
      {(error || selectionError || countryError || catalogError) && <div className="error" role="alert">{error || selectionError || countryError || catalogError}</div>}
      <div className="formGrid">
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-registration-country`}>{t("modules:vehicles.registrationCountry")}</label>
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
            <option value="">{t("modules:vehicles.selectCountry")}</option>
            {countries.map((country) => <option key={country.code} value={country.code}>{t(`common:countries.${country.code}`)}</option>)}
          </select>
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-license-plate`}>{t("common:labels.licencePlate")}</label>
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
            placeholder={selectedCountry?.placeholder ?? t("modules:vehicles.selectCountryFirst")}
            aria-describedby={`${fieldPrefix}-license-plate-help`}
            aria-invalid={Boolean(plateError)}
            disabled={!form.registration_country}
            inputMode="text"
            autoComplete="off"
            maxLength={9}
            required
          />
          <span id={`${fieldPrefix}-license-plate-help`} className={plateError ? "errorText" : "muted"} aria-live="polite">
            {plateError ?? selectedCountry?.helper_text.join(" · ") ?? t("modules:vehicles.selectCountryHelp")}
          </span>
          {mode === "edit" && !initialValues?.registration_country && (
            <span className="errorText" role="alert">{t("modules:vehicles.countryRequiredUpdate")}</span>
          )}
        </div>
        <div className="formRow">
          <div className="catalogFieldHeader">
            <label htmlFor={`${fieldPrefix}-brand`}>{t("common:labels.brand")}</label>
            {canManageCatalog && !addingBrand && (
              <button type="button" className="linkButton catalogCreateLink" onClick={() => { setAddingBrand(true); setCatalogError(null); }} disabled={loadingBrands || savingCatalog}>{t("modules:vehicles.addBrand")}</button>
            )}
          </div>
          <SearchableCombobox
            id={`${fieldPrefix}-brand`}
            options={brands}
            value={form.brand_id}
            selectedLabel={fallbackLabels.brand}
            onChange={(brandId) => {
              setFallbackLabels({ brand: undefined, model: undefined });
              setSelectionError(null);
              setCatalogError(null);
              setAddingModel(false);
              setForm((current) => ({ ...current, brand_id: brandId, model_id: null }));
            }}
            placeholder={loadingBrands ? t("modules:vehicles.loadingBrands") : t("modules:vehicles.selectBrand")}
            searchPlaceholder={t("modules:vehicles.searchBrands")}
            emptyText={t("modules:vehicles.emptyBrands")}
            loadingText={t("modules:vehicles.loadingBrands")}
            loading={loadingBrands}
            disabled={addingBrand || savingCatalog}
            error={brandError}
            required
          />
          {brandError && <button className="linkButton retryButton" type="button" onClick={() => loadBrands(true)}>{t("modules:vehicles.retryBrands")}</button>}
          {canManageCatalog && addingBrand && (
            <div className="catalogCreateControls">
              <input
                className="input"
                value={newBrandName}
                onChange={(event) => setNewBrandName(event.target.value)}
                onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void saveBrand(); } }}
                placeholder={t("modules:vehicles.newBrandName")}
                aria-label={t("modules:vehicles.newBrandName")}
                maxLength={255}
                disabled={savingCatalog}
              />
              <button type="button" className="secondaryButton smallButton" onClick={() => void saveBrand()} disabled={!newBrandName.trim() || savingCatalog}>{t("modules:vehicles.saveBrand")}</button>
              <button type="button" className="linkButton" onClick={() => { setAddingBrand(false); setNewBrandName(""); setCatalogError(null); }} disabled={savingCatalog}>{t("common:actions.cancel")}</button>
            </div>
          )}
        </div>
        <div className="formRow">
          <div className="catalogFieldHeader">
            <label htmlFor={`${fieldPrefix}-model`}>{t("common:labels.model")}</label>
            {canManageCatalog && form.brand_id !== null && !addingModel && (
              <button type="button" className="linkButton catalogCreateLink" onClick={() => { setAddingModel(true); setCatalogError(null); }} disabled={loadingModels || savingCatalog}>{t("modules:vehicles.addModel")}</button>
            )}
          </div>
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
            placeholder={form.brand_id === null ? t("modules:vehicles.selectBrandFirst") : t("modules:vehicles.selectModel")}
            searchPlaceholder={t("modules:vehicles.searchModels")}
            emptyText={t("modules:vehicles.emptyModels")}
            loadingText={t("modules:vehicles.loadingModels")}
            loading={loadingModels}
            disabled={form.brand_id === null || addingModel || savingCatalog}
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
                  .catch(() => setModelError(t("modules:vehicles.modelLoadError")))
                  .finally(() => setLoadingModels(false));
              }}
            >
              {t("modules:vehicles.retryModels")}
            </button>
          )}
          {canManageCatalog && form.brand_id !== null && addingModel && (
            <div className="catalogCreateControls">
              <input
                className="input"
                value={newModelName}
                onChange={(event) => setNewModelName(event.target.value)}
                onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void saveModel(); } }}
                placeholder={t("modules:vehicles.newModelName")}
                aria-label={t("modules:vehicles.newModelName")}
                maxLength={255}
                disabled={savingCatalog}
              />
              <button type="button" className="secondaryButton smallButton" onClick={() => void saveModel()} disabled={!newModelName.trim() || savingCatalog}>{t("modules:vehicles.saveModel")}</button>
              <button type="button" className="linkButton" onClick={() => { setAddingModel(false); setNewModelName(""); setCatalogError(null); }} disabled={savingCatalog}>{t("common:actions.cancel")}</button>
            </div>
          )}
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-fuel-type`}>{t("modules:vehicles.fuelType")}</label>
          <select id={`${fieldPrefix}-fuel-type`} className="select" value={form.fuel_type} onChange={(event) => setForm({ ...form, fuel_type: event.target.value })} required>
            {FUEL_TYPES.map((fuel) => <option key={fuel} value={fuel}>{t(`common:types.${fuel}`)}</option>)}
          </select>
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-location`}>{t("common:labels.location")}</label>
          <input id={`${fieldPrefix}-location`} className="input" value={form.vehicle_location} onChange={(event) => setForm({ ...form, vehicle_location: event.target.value })} required />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-category`}>{t("modules:vehicles.category")}</label>
          <input id={`${fieldPrefix}-category`} className="input" value={form.vehicle_category ?? ""} onChange={(event) => setForm({ ...form, vehicle_category: event.target.value || null })} placeholder={t("modules:vehicles.categoryPlaceholder")} />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-year`}>{t("modules:vehicles.year")}</label>
          <input id={`${fieldPrefix}-year`} className="input" type="number" min="1900" max="2100" value={form.year ?? ""} onChange={(event) => setForm({ ...form, year: event.target.value ? Number(event.target.value) : null })} />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-vin`}>{t("modules:vehicles.vin")}</label>
          <input id={`${fieldPrefix}-vin`} className="input" maxLength={50} value={form.vin_number ?? ""} onChange={(event) => setForm({ ...form, vin_number: event.target.value || null })} />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-engine-cc`}>{t("modules:vehicles.engineCc")}</label>
          <input id={`${fieldPrefix}-engine-cc`} className="input" type="number" min="50" max="10000" value={form.engine_cc ?? ""} onChange={(event) => setForm({ ...form, engine_cc: event.target.value ? Number(event.target.value) : null })} />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-odometer`}>{t("modules:vehicles.odometerKm")}</label>
          <input id={`${fieldPrefix}-odometer`} className="input" type="number" min="0" max="2000000" value={form.odometer_km ?? ""} onChange={(event) => setForm({ ...form, odometer_km: event.target.value ? Number(event.target.value) : null })} />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-acquisition-date`}>{t("modules:vehicles.acquisitionDate")}</label>
          <input id={`${fieldPrefix}-acquisition-date`} className="input" type="date" value={form.acquisition_date ?? ""} onChange={(event) => setForm({ ...form, acquisition_date: event.target.value || null })} />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-ownership-type`}>{t("modules:vehicles.ownershipType")}</label>
          <select id={`${fieldPrefix}-ownership-type`} className="select" value={form.ownership_type} onChange={(event) => setForm({ ...form, ownership_type: event.target.value as VehicleFormValues["ownership_type"] })}>
            {OWNERSHIP_TYPES.map((value) => <option key={value} value={value}>{t(`common:types.${value}`, { defaultValue: value })}</option>)}
          </select>
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-purchase-price`}>{t("modules:vehicles.purchasePrice")}</label>
          <input id={`${fieldPrefix}-purchase-price`} className="input" type="number" min="0" step="0.01" value={form.purchase_price ?? ""} onChange={(event) => setForm({ ...form, purchase_price: event.target.value ? Number(event.target.value) : null })} />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-supplier-id`}>{t("modules:vehicles.supplierId")}</label>
          <input id={`${fieldPrefix}-supplier-id`} className="input" type="number" min="1" value={form.supplier_id ?? ""} onChange={(event) => setForm({ ...form, supplier_id: event.target.value ? Number(event.target.value) : null })} />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-lease-start`}>{t("modules:vehicles.leaseStart")}</label>
          <input id={`${fieldPrefix}-lease-start`} className="input" type="date" value={form.lease_start ?? ""} onChange={(event) => setForm({ ...form, lease_start: event.target.value || null })} />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-lease-end`}>{t("modules:vehicles.leaseEnd")}</label>
          <input id={`${fieldPrefix}-lease-end`} className="input" type="date" value={form.lease_end ?? ""} onChange={(event) => setForm({ ...form, lease_end: event.target.value || null })} />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-lease-payment`}>{t("modules:vehicles.monthlyLeasePayment")}</label>
          <input id={`${fieldPrefix}-lease-payment`} className="input" type="number" min="0" step="0.01" value={form.monthly_lease_payment ?? ""} onChange={(event) => setForm({ ...form, monthly_lease_payment: event.target.value ? Number(event.target.value) : null })} />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-warranty-expiry`}>{t("modules:vehicles.warrantyExpiry")}</label>
          <input id={`${fieldPrefix}-warranty-expiry`} className="input" type="date" value={form.warranty_expiry ?? ""} onChange={(event) => setForm({ ...form, warranty_expiry: event.target.value || null })} />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-service-years`}>{t("modules:vehicles.expectedServiceYears")}</label>
          <input id={`${fieldPrefix}-service-years`} className="input" type="number" min="1" max="100" value={form.expected_service_years ?? ""} onChange={(event) => setForm({ ...form, expected_service_years: event.target.value ? Number(event.target.value) : null })} />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-service-km`}>{t("modules:vehicles.expectedServiceKm")}</label>
          <input id={`${fieldPrefix}-service-km`} className="input" type="number" min="1" value={form.expected_service_km ?? ""} onChange={(event) => setForm({ ...form, expected_service_km: event.target.value ? Number(event.target.value) : null })} />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-depreciation`}>{t("modules:vehicles.depreciationMethod")}</label>
          <select id={`${fieldPrefix}-depreciation`} className="select" value={form.depreciation_method} onChange={(event) => setForm({ ...form, depreciation_method: event.target.value as VehicleFormValues["depreciation_method"] })}>
            {DEPRECIATION_METHODS.map((value) => <option key={value} value={value}>{t(`common:types.${value}`, { defaultValue: value })}</option>)}
          </select>
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-residual-value`}>{t("modules:vehicles.residualValue")}</label>
          <input id={`${fieldPrefix}-residual-value`} className="input" type="number" min="0" step="0.01" value={form.residual_value ?? ""} onChange={(event) => setForm({ ...form, residual_value: event.target.value ? Number(event.target.value) : null })} />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-tank-capacity`}>{t("modules:vehicles.fuelTankCapacity")}</label>
          <input id={`${fieldPrefix}-tank-capacity`} className="input" type="number" min="0.01" step="0.01" value={form.fuel_tank_capacity_l ?? ""} onChange={(event) => setForm({ ...form, fuel_tank_capacity_l: event.target.value ? Number(event.target.value) : null })} />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-battery-capacity`}>{t("modules:vehicles.batteryCapacity")}</label>
          <input id={`${fieldPrefix}-battery-capacity`} className="input" type="number" min="0.01" step="0.01" value={form.battery_capacity_kwh ?? ""} onChange={(event) => setForm({ ...form, battery_capacity_kwh: event.target.value ? Number(event.target.value) : null })} />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-sale-date`}>{t("modules:vehicles.saleDate")}</label>
          <input id={`${fieldPrefix}-sale-date`} className="input" type="date" value={form.sale_date ?? ""} onChange={(event) => setForm({ ...form, sale_date: event.target.value || null })} />
        </div>
        <div className="formRow">
          <label htmlFor={`${fieldPrefix}-sale-price`}>{t("modules:vehicles.salePrice")}</label>
          <input id={`${fieldPrefix}-sale-price`} className="input" type="number" min="0" step="0.01" value={form.sale_price ?? ""} onChange={(event) => setForm({ ...form, sale_price: event.target.value ? Number(event.target.value) : null })} />
        </div>
        <div className="formRow formRowWide">
          <label htmlFor={`${fieldPrefix}-disposal-reason`}>{t("modules:vehicles.disposalReason")}</label>
          <textarea id={`${fieldPrefix}-disposal-reason`} className="textarea" maxLength={1000} value={form.disposal_reason ?? ""} onChange={(event) => setForm({ ...form, disposal_reason: event.target.value || null })} />
        </div>
        {mode === "edit" && <div className="formRow">
          <label htmlFor={`${fieldPrefix}-status`}>{t("common:labels.status")}</label>
          <select id={`${fieldPrefix}-status`} className="select" value={form.status} onChange={(event) => setForm({ ...form, status: Number(event.target.value) })} required>
            {VEHICLE_STATUSES.map((status) => <option key={status.value} value={status.value}>{t(`common:${status.labelKey}`)}</option>)}
          </select>
        </div>}
      </div>
      <div className="actions dialogActions">
        {onCancel && <button className="secondaryButton" type="button" onClick={onCancel} disabled={submitting || savingCatalog}>{t("common:actions.cancel")}</button>}
        <button className="button" type="submit" disabled={submitting || loadingBrands || loadingModels || addingBrand || addingModel || savingCatalog}>
          {submitting ? (mode === "edit" ? t("modules:vehicles.updating") : t("modules:vehicles.creating")) : (mode === "edit" ? t("modules:vehicles.update") : t("modules:vehicles.create"))}
        </button>
      </div>
    </form>
  );
}
