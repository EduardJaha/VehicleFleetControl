import { apiGet, apiPost, apiPut } from "@/lib/api";

export type TelematicsProvider = "generic" | "geotab" | "samsara" | "motive" | "oem";
export interface TelematicsSettings {
  min_confidence: number;
  max_reading_age_seconds: number;
  online_after_seconds: number;
}
export interface IntegrationConnection {
  id: number;
  provider: TelematicsProvider;
  status: "NotConfigured" | "Ready" | "Disabled";
  last_sync_at: string | null;
  last_error: string | null;
  settings: TelematicsSettings;
}
export interface ExternalVehicleMapping {
  id: number;
  connection_id: number;
  vehicle_id: number;
  external_vehicle_id: string;
  vin: string | null;
  external_device_id: string | null;
  odometer_sync_enabled: boolean;
}
export type TelematicsKind = "location" | "trip" | "odometer" | "engine_hours" | "fuel_level" | "battery_level" | "diagnostic" | "behavior";
export interface TelematicsEvent {
  id: number;
  vehicle_id: number;
  connection_id: number;
  provider: TelematicsProvider;
  external_event_id: string;
  occurred_at: string;
  received_at: string;
}
export interface VehicleLocationEvent extends TelematicsEvent {
  latitude: number;
  longitude: number;
  speed_kph: number | null;
  heading: number | null;
  ignition: boolean | null;
  idling: boolean | null;
}
export interface Trip extends TelematicsEvent {
  ended_at: string;
  distance_km: number;
  idle_seconds: number;
}
export interface OdometerEvent extends TelematicsEvent {
  odometer_km: number;
  confidence: number;
  sync_result: string;
}
export interface EngineHourEvent extends TelematicsEvent { engine_hours: number }
export interface FuelLevelEvent extends TelematicsEvent { fuel_percent: number }
export interface BatteryLevelEvent extends TelematicsEvent { soc_percent: number }
export interface DiagnosticCodeEvent extends TelematicsEvent { code: string; active: boolean }
export interface DriverBehaviorEvent extends TelematicsEvent { behavior: string; duration_seconds: number | null }
export interface VehicleTelematicsSummary {
  vehicle_id: number;
  connectivity: "unknown" | "online" | "offline";
  last_seen_at: string | null;
  last_location: VehicleLocationEvent | null;
  mileage_today_km: number | null;
  mileage_basis: "observed_odometer_delta";
  timezone: string;
  idling_today_seconds: number | null;
  idling_basis: "completed_trips_inside_day";
  diagnostic_alerts: DiagnosticCodeEvent[];
  latest_readings: {
    odometer: OdometerEvent | null;
    engine_hours: EngineHourEvent | null;
    fuel_level: FuelLevelEvent | null;
    battery_level: BatteryLevelEvent | null;
  };
}
const base = "/telematics";
// Future UI consumes real data through the existing authenticated client.
export const telematicsApi = {
  connections: () => apiGet<IntegrationConnection[]>(`${base}/connections`),
  createConnection: (payload: { provider: TelematicsProvider; credentials_reference?: string; settings?: Partial<TelematicsSettings> }) =>
    apiPost<IntegrationConnection>(`${base}/connections`, payload),
  configureConnection: (id: number, payload: { enabled: boolean; credentials_reference?: string; settings?: Partial<TelematicsSettings> }) =>
    apiPut<IntegrationConnection>(`${base}/connections/${id}`, payload),
  mappings: (id: number) => apiGet<ExternalVehicleMapping[]>(`${base}/connections/${id}/mappings`),
  mapVehicle: (id: number, payload: { vehicle_id: number; external_vehicle_id: string; vin?: string; external_device_id?: string }) =>
    apiPost<ExternalVehicleMapping>(`${base}/connections/${id}/mappings`, payload),
  odometerPolicy: (id: number, enabled: boolean, release_manual_override = false) =>
    apiPut<ExternalVehicleMapping>(`${base}/mappings/${id}/odometer-policy`, { enabled, release_manual_override }),
  summary: (id: number) => apiGet<VehicleTelematicsSummary>(`${base}/vehicles/${id}/summary`),
  trips: (id: number, beforeId?: number) => apiGet<Trip[]>(`${base}/vehicles/${id}/events/trip${beforeId === undefined ? "" : `?before_id=${beforeId}`}`),
};
