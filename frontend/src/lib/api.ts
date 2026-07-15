import type {
  Inspection, MaintenanceSummary, MaintenanceTimelineEvent, PageResult, ServiceReminder,
  VehicleMaintenanceSummary, VehicleServiceDetail, VehicleServiceOverview, WorkOrder
} from "@/lib/types";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
export const API_ORIGIN = API_BASE_URL.replace(/\/api\/v1\/?$/, "");
export const AUTH_TOKEN_KEY = "vehicle_fleet_control_token";

export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(AUTH_TOKEN_KEY);
}

export function setAuthToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(AUTH_TOKEN_KEY, token);
}

export function clearAuthToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(AUTH_TOKEN_KEY);
  window.dispatchEvent(new Event("auth:logout"));
}

function authHeaders(): HeadersInit {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    if (response.status === 401 && typeof window !== "undefined") {
      clearAuthToken();
    }
    let message = `API error ${response.status}`;
    try {
      const body = await response.json();
      message = body.detail ?? body.message ?? message;
    } catch {
      const text = await response.text();
      message = text || message;
    }
    throw new Error(message);
  }

  const text = await response.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

export function buildQuery(params: Record<string, string | number | boolean | null | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== "") {
      query.set(key, String(value));
    }
  });
  const text = query.toString();
  return text ? `?${text}` : "";
}

export function fileHref(path?: string | null): string {
  if (!path) return "#";
  if (path.startsWith("http://") || path.startsWith("https://")) return path;

  let normalized = path.replaceAll("\\\\", "/").replace(/^\/+/, "");
  if (normalized.includes("/uploads/")) {
    normalized = `uploads/${normalized.split("/uploads/", 2)[1]}`;
  }
  if (!normalized.startsWith("uploads/")) {
    normalized = `uploads/${normalized.split("/").pop() ?? normalized}`;
  }
  return `${API_ORIGIN}/${normalized}`;
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store", headers: authHeaders() });
  return handleResponse<T>(response);
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body)
  });
  return handleResponse<T>(response);
}

export async function apiPostForm<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: authHeaders(),
    body
  });
  return handleResponse<T>(response);
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body)
  });
  return handleResponse<T>(response);
}

export async function apiDelete<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { method: "DELETE", headers: authHeaders() });
  return handleResponse<T>(response);
}

export async function apiDownload(path: string, fallbackFilename: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store", headers: authHeaders() });
  if (!response.ok) {
    await handleResponse<never>(response);
    return;
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^"]+)"?/i.exec(disposition);
  const filename = match?.[1] ?? fallbackFilename;
  const href = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = href;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(href);
}

export const maintenanceApi = {
  getSummary: () => apiGet<MaintenanceSummary>("/maintenance/summary"),
  getWorkOrders: (params: Record<string, string | number | boolean | null | undefined>) =>
    apiGet<PageResult<WorkOrder>>(`/work-orders${buildQuery(params)}`),
  getWorkOrder: (id: number | string) => apiGet<WorkOrder>(`/work-orders/${id}`),
  getServices: (params: Record<string, string | number | boolean | null | undefined>) =>
    apiGet<PageResult<VehicleServiceOverview>>(`/services/history${buildQuery(params)}`),
  getService: (id: number | string) => apiGet<VehicleServiceDetail>(`/services/id/${id}`),
  getReminders: (params: Record<string, string | number | boolean | null | undefined>) =>
    apiGet<PageResult<ServiceReminder>>(`/services/reminders${buildQuery(params)}`),
  getInspections: (params: Record<string, string | number | boolean | null | undefined>) =>
    apiGet<PageResult<Inspection>>(`/inspections${buildQuery(params)}`),
  getInspection: (id: number | string) => apiGet<Inspection>(`/inspections/${id}`),
  getVehicleSummary: (vehicleId: number | string) =>
    apiGet<VehicleMaintenanceSummary>(`/vehicles/${vehicleId}/maintenance-summary`),
  getVehicleTimeline: (vehicleId: number | string, page = 1, pageSize = 20) =>
    apiGet<PageResult<MaintenanceTimelineEvent>>(`/vehicles/${vehicleId}/maintenance-timeline${buildQuery({ page, page_size: pageSize })}`)
};
