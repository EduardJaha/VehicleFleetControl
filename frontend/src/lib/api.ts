import type {
  ApiMessage, Attachment, Inspection, MaintenanceSummary, MaintenanceTimelineEvent, PageResult, ServiceReminder,
  VehicleBrand, VehicleMaintenanceSummary, VehicleModel, VehicleServiceDetail,
  VehicleServiceOverview, WorkOrder, WorkOrderCompletionPayload, WorkOrderCompletionResult,
  RegistrationCountryOption, VehicleAssignment, VehicleAssignmentCompletePayload,
  VehicleAssignmentPayload, VehicleAssignmentStartPayload, VehicleCheckoutPayload,
  VehicleCheckoutResult, VehicleConditionRecord, VehicleReturnPayload, VehicleReturnResult
} from "@/lib/types";
import i18n from "@/i18n";
import { getActiveLanguage } from "@/i18n/language";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
export const API_ORIGIN = API_BASE_URL.replace(/\/api\/v1\/?$/, "");
export function clearAuthState(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event("auth:logout"));
}

function authHeaders(): HeadersInit {
  return { "Accept-Language": getActiveLanguage() };
}

async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, { credentials: "include", ...init });
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(i18n.t("errors:network"));
    }
    throw error;
  }
}

function validationIssueMessage(issue: unknown): string | null {
  if (!issue || typeof issue !== "object") return null;
  const record = issue as { loc?: unknown; msg?: unknown };
  if (typeof record.msg !== "string") return null;
  const message = record.msg.replace(/^Value error,\s*/i, "");
  if (!Array.isArray(record.loc)) return message;
  const field = [...record.loc].reverse().find((part) => typeof part === "string" && part !== "body");
  return typeof field === "string" ? `${field.replaceAll("_", " ")}: ${message}` : message;
}

function translateErrorCode(code: string, params?: Record<string, unknown>): string | null {
  const key = `errors:${code}`;
  return i18n.exists(key) ? i18n.t(key, params ?? {}) : null;
}

function translateFieldName(field: string): string {
  const normalized = field.split(".").at(-1) ?? field;
  const key = `errors:fields.${normalized}`;
  return i18n.exists(key) ? i18n.t(key) : normalized.replaceAll("_", " ");
}

function apiErrorMessage(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const record = body as {
    code?: unknown;
    detail?: unknown;
    message?: unknown;
    params?: unknown;
    field_errors?: unknown;
  };
  const params = record.params && typeof record.params === "object"
    ? record.params as Record<string, unknown>
    : undefined;
  if (typeof record.code === "string") {
    const translated = translateErrorCode(record.code, params);
    if (Array.isArray(record.field_errors)) {
      const fields = record.field_errors.map((item) => {
        if (!item || typeof item !== "object") return null;
        const issue = item as { field?: unknown; code?: unknown; params?: unknown };
        if (typeof issue.code !== "string") return null;
        const issueParams = issue.params && typeof issue.params === "object"
          ? issue.params as Record<string, unknown>
          : {};
        return translateErrorCode(issue.code, {
          field: typeof issue.field === "string" ? translateFieldName(issue.field) : "",
          ...issueParams
        });
      }).filter((message): message is string => Boolean(message));
      if (fields.length) return fields.join(" ");
    }
    if (translated) return translated;
  }
  if (typeof record.detail === "string") return record.detail;
  if (record.detail && typeof record.detail === "object") {
    const detail = record.detail as { code?: unknown; message?: unknown; params?: unknown };
    if (typeof detail.code === "string") {
      const detailParams = detail.params && typeof detail.params === "object"
        ? detail.params as Record<string, unknown>
        : {};
      return translateErrorCode(detail.code, detailParams)
        ?? (typeof detail.message === "string" ? detail.message : null);
    }
  }
  if (Array.isArray(record.detail)) {
    const messages = record.detail.map(validationIssueMessage).filter((message): message is string => Boolean(message));
    if (messages.length > 0) return messages.join(" ");
  }
  return typeof record.message === "string" ? record.message : null;
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    if (response.status === 401 && typeof window !== "undefined") {
      clearAuthState();
    }
    let message = i18n.t("errors:api");
    try {
      const body: unknown = await response.json();
      if (body && typeof body === "object" && "code" in body && body.code === "password_change_required" && typeof window !== "undefined") {
        window.location.assign("/account/password");
      }
      message = apiErrorMessage(body) ?? message;
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
  if (path.startsWith("/api/v1/")) return `${API_ORIGIN}${path}`;

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
  const response = await apiFetch(`${API_BASE_URL}${path}`, { cache: "no-store", headers: authHeaders() });
  return handleResponse<T>(response);
}

export async function apiGetBlob(path: string): Promise<Blob> {
  const response = await apiFetch(`${API_BASE_URL}${path}`, { cache: "no-store", headers: authHeaders() });
  if (!response.ok) {
    await handleResponse<never>(response);
  }
  return response.blob();
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const response = await apiFetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body)
  });
  return handleResponse<T>(response);
}

export async function apiPostForm<T>(path: string, body: FormData): Promise<T> {
  const response = await apiFetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: authHeaders(),
    body
  });
  return handleResponse<T>(response);
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const response = await apiFetch(`${API_BASE_URL}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body)
  });
  return handleResponse<T>(response);
}

export async function apiDelete<T>(path: string): Promise<T> {
  const response = await apiFetch(`${API_BASE_URL}${path}`, { method: "DELETE", headers: authHeaders() });
  return handleResponse<T>(response);
}

let vehicleBrandCache: Promise<VehicleBrand[]> | null = null;
const vehicleModelCache = new Map<number, Promise<VehicleModel[]>>();
let registrationCountryCache: Promise<RegistrationCountryOption[]> | null = null;

function alphabetically<T extends { name: string }>(items: T[]): T[] {
  return [...items].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
}

export const vehicleCatalogApi = {
  getBrands(force = false): Promise<VehicleBrand[]> {
    if (force) vehicleBrandCache = null;
    if (!vehicleBrandCache) {
      vehicleBrandCache = apiGet<VehicleBrand[]>("/vehicle-catalog/brands?limit=500")
        .then(alphabetically)
        .catch((error) => {
          vehicleBrandCache = null;
          throw error;
        });
    }
    return vehicleBrandCache;
  },
  getModelsByBrand(brandId: number, force = false): Promise<VehicleModel[]> {
    if (force) vehicleModelCache.delete(brandId);
    let request = vehicleModelCache.get(brandId);
    if (!request) {
      request = apiGet<VehicleModel[]>(`/vehicle-catalog/brands/${brandId}/models?limit=500`)
        .then(alphabetically)
        .catch((error) => {
          vehicleModelCache.delete(brandId);
          throw error;
        });
      vehicleModelCache.set(brandId, request);
    }
    return request;
  },
  async createBrand(name: string): Promise<VehicleBrand> {
    const brand = await apiPost<VehicleBrand>("/vehicle-catalog/brands", { name, is_active: true });
    vehicleBrandCache = null;
    return brand;
  },
  async createModel(brandId: number, name: string): Promise<VehicleModel> {
    const model = await apiPost<VehicleModel>("/vehicle-catalog/models", {
      brand_id: brandId,
      name,
      is_active: true
    });
    vehicleModelCache.delete(brandId);
    return model;
  }
};

export const vehicleRegistrationApi = {
  getCountries(force = false): Promise<RegistrationCountryOption[]> {
    if (force) registrationCountryCache = null;
    if (!registrationCountryCache) {
      registrationCountryCache = apiGet<RegistrationCountryOption[]>("/vehicle-registration/countries")
        .catch((error) => {
          registrationCountryCache = null;
          throw error;
        });
    }
    return registrationCountryCache;
  }
};

export async function apiDownload(path: string, fallbackFilename: string): Promise<void> {
  const url = path.startsWith("/api/v1/") ? `${API_ORIGIN}${path}` : `${API_BASE_URL}${path}`;
  const response = await apiFetch(url, { cache: "no-store", headers: authHeaders() });
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

export function apiDownloadFile(path: string, fallbackFilename: string): Promise<void> {
  if (path.startsWith("/api/v1/")) return apiDownload(path, fallbackFilename);
  return apiDownload(`/files/legacy/download${buildQuery({ path })}`, fallbackFilename);
}

export const filesApi = {
  list: (entityType: string, entityId: number | string) =>
    apiGet<Attachment[]>(`/files${buildQuery({ entity_type: entityType, entity_id: entityId })}`),
  download: (file: Attachment) =>
    apiDownload(`/files/${file.id}/download`, file.original_filename)
};

export const maintenanceApi = {
  getSummary: () => apiGet<MaintenanceSummary>("/maintenance/summary"),
  getWorkOrders: (params: Record<string, string | number | boolean | null | undefined>) =>
    apiGet<PageResult<WorkOrder>>(`/work-orders${buildQuery(params)}`),
  getWorkOrder: (id: number | string) => apiGet<WorkOrder>(`/work-orders/${id}`),
  completeWorkOrder: (id: number | string, payload: WorkOrderCompletionPayload) =>
    apiPost<WorkOrderCompletionResult>(`/work-orders/${id}/complete`, payload),
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

export const vehicleAssignmentsApi = {
  list: (params: Record<string, string | number | boolean | null | undefined>) =>
    apiGet<PageResult<VehicleAssignment>>(`/vehicle-assignments${buildQuery(params)}`),
  get: (id: number | string) => apiGet<VehicleAssignment>(`/vehicle-assignments/${id}`),
  create: (payload: VehicleAssignmentPayload) =>
    apiPost<VehicleAssignment>("/vehicle-assignments", payload),
  update: (id: number | string, payload: VehicleAssignmentPayload) =>
    apiPut<VehicleAssignment>(`/vehicle-assignments/${id}`, payload),
  start: (id: number | string, payload: VehicleAssignmentStartPayload) =>
    apiPost<VehicleAssignment>(`/vehicle-assignments/${id}/start`, payload),
  complete: (id: number | string, payload: VehicleAssignmentCompletePayload) =>
    apiPost<VehicleAssignment>(`/vehicle-assignments/${id}/complete`, payload),
  checkout: (payload: VehicleCheckoutPayload) =>
    apiPost<VehicleCheckoutResult>("/vehicle-assignments/check-out", payload),
  returnVehicle: (id: number | string, payload: VehicleReturnPayload) =>
    apiPost<VehicleReturnResult>(`/vehicle-assignments/${id}/return`, payload),
  conditions: (id: number | string) =>
    apiGet<VehicleConditionRecord[]>(`/vehicle-assignments/${id}/conditions`),
  cancel: (id: number | string) =>
    apiPost<VehicleAssignment>(`/vehicle-assignments/${id}/cancel`, {}),
  archive: (id: number | string) =>
    apiDelete<ApiMessage>(`/vehicle-assignments/${id}`),
  restore: (id: number | string) =>
    apiPost<VehicleAssignment>(`/vehicle-assignments/${id}/restore`, {})
};
