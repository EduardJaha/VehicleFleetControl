import { API_BASE_URL } from "@/lib/api";
import { getActiveLanguage } from "@/i18n/language";
import i18n from "@/i18n";
import type { CurrentUser, Inspection } from "@/lib/types";

export type Owner = { user_id: number; company_id: number };
export type Photo = { id: string; itemId?: number; name: string; blob?: Blob; attachmentId?: number };
export type Draft = {
  id: string; owner: Owner; kind: "inspection" | "accident"; status: "Local Draft" | "Pending Sync" | "Syncing" | "Synced" | "Conflict" | "Failed";
  revision?: number; label: string; payload: Record<string, unknown>; inspection?: Inspection; serverId?: number;
  photos: Photo[]; updated: number; error?: string; attempts: number; retryAt?: number;
};
const DB = "vfc-mobile-v1";
const OWNER_KEY = "vfc-mobile-owner";
const changed = () => window.dispatchEvent(new Event("mobile:drafts"));
export const ownerOf = (u: CurrentUser): Owner => ({ user_id: u.id, company_id: u.company_id });
export const sameOwner = (a: Owner, b: Owner) => a.user_id === b.user_id && a.company_id === b.company_id;
export function localOwner(): Owner | null {
  try { return JSON.parse(localStorage.getItem(OWNER_KEY) || "null"); } catch { return null; }
}
export function rememberOwner(owner: Owner) { localStorage.setItem(OWNER_KEY, JSON.stringify(owner)); }
function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB, 1);
    request.onupgradeneeded = () => request.result.createObjectStore("drafts", { keyPath: "id" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
export async function drafts(owner: Owner): Promise<Draft[]> {
  const db = await database();
  return new Promise((resolve, reject) => {
    const tx = db.transaction("drafts", "readonly");
    const req = tx.objectStore("drafts").getAll();
    req.onsuccess = () => resolve((req.result as Draft[]).filter(d => sameOwner(d.owner, owner)));
    req.onerror = () => reject(req.error);
    tx.oncomplete = () => db.close();
  });
}
export async function saveDraft(draft: Draft): Promise<void> {
  const active = localOwner();
  if (!active || !sameOwner(active, draft.owner)) throw new Error(i18n.t("modules:mobile.signIn"));
  const db = await database();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction("drafts", "readwrite");
    const store = tx.objectStore("drafts");
    const current = store.get(draft.id);
    let revision = draft.revision || 0;
    current.onsuccess = () => {
      const activeScope = localOwner();
      if (!activeScope || !sameOwner(activeScope, draft.owner) || (!current.result && revision > 0)) { tx.abort(); return; }
      if (current.result && (current.result.revision || 0) !== revision) { tx.abort(); return; }
      revision += 1; store.put({ ...draft, revision });
    };
    tx.oncomplete = () => { draft.revision = revision; db.close(); resolve(); };
    tx.onabort = () => { db.close(); reject(tx.error || new Error(i18n.t("modules:mobile.storageError"))); };
  });
  changed();
}
export async function removeDraft(id: string) {
  const db = await database();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction("drafts", "readwrite"); tx.objectStore("drafts").delete(id);
    tx.oncomplete = () => { db.close(); resolve(); }; tx.onabort = () => { db.close(); reject(tx.error); };
  });
  changed();
}
export async function clearOffline() {
  localStorage.removeItem(OWNER_KEY);
  Object.keys(localStorage).filter(k => k.startsWith("vfc-mobile-pack-")).forEach(k => localStorage.removeItem(k));
  const db = await database();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction("drafts", "readwrite"); tx.objectStore("drafts").clear();
    tx.oncomplete = () => { db.close(); resolve(); }; tx.onabort = () => { db.close(); reject(tx.error); };
  });
  changed();
}
export async function reserveLocal(owner: Owner) {
  const active = localOwner();
  if (!active || !sameOwner(active, owner)) throw new Error(i18n.t("modules:mobile.signIn"));
  const all = await drafts(owner);
  if (all.filter(d => d.status !== "Synced").length >= 30) throw new Error(i18n.t("modules:mobile.storageLimit"));
  // Remove only acknowledged local copies; never erase unsent evidence automatically.
  for (const d of all) if (d.status === "Synced" && Date.now() - d.updated > 7 * 86400000) await removeDraft(d.id);
  await navigator.storage?.persist?.();
  const current = localOwner();
  if (!current || !sameOwner(current, owner)) throw new Error(i18n.t("modules:mobile.signIn"));
}
export function fromInspection(inspection: Inspection, owner: Owner, id = crypto.randomUUID()): Draft {
  return { id, owner, kind: "inspection", status: "Local Draft", label: inspection.license_plate, inspection,
    serverId: inspection.id, photos: [], updated: Date.now(), attempts: 0,
    payload: { vehicle_id: inspection.vehicle_id, driver_id: inspection.driver_id, template_id: inspection.template_id,
      inspection_type: inspection.inspection_type, inspection_date: inspection.inspection_date,
      notes: inspection.notes, complete: true, items: inspection.items } };
}
class SyncError extends Error { constructor(public status: number, message: string) { super(message); } }
export async function mobileRequest<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { method: body ? "POST" : "GET", credentials: "include", cache: "no-store",
    headers: { "Content-Type": "application/json", "Accept-Language": getActiveLanguage() },
    body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(45000) });
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    throw new SyncError(response.status, result.message || result.detail?.message || (typeof result.detail === "string" ? result.detail : i18n.t("modules:mobile.failed")));
  }
  return response.json();
}
export async function compressPhoto(file: File): Promise<Blob> {
  if (!["image/jpeg", "image/png", "image/webp"].includes(file.type) || file.size > 20 * 1024 * 1024) throw new Error(i18n.t("modules:mobile.photoLimit"));
  const image = await createImageBitmap(file);
  try {
    if (image.width * image.height > 60000000) throw new Error(i18n.t("modules:mobile.photoLimit"));
    const scale = Math.min(1, 2560 / Math.max(image.width, image.height));
    const canvas = document.createElement("canvas"); canvas.width = Math.round(image.width * scale); canvas.height = Math.round(image.height * scale);
    const ctx = canvas.getContext("2d"); if (!ctx) throw new Error(i18n.t("modules:mobile.photoLimit"));
    ctx.fillStyle = "white"; ctx.fillRect(0, 0, canvas.width, canvas.height); ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob(b => b ? resolve(b) : reject(new Error(i18n.t("modules:mobile.photoLimit"))), "image/jpeg", 0.9));
    if (blob.size > 8 * 1024 * 1024) throw new Error(i18n.t("modules:mobile.photoLimit"));
    return blob;
  } finally { image.close(); }
}
export async function addPhoto(draft: Draft, file: File, itemId?: number): Promise<Draft> {
  if (draft.photos.length >= 20) throw new Error(i18n.t("modules:mobile.photoLimit"));
  const blob = await compressPhoto(file);
  const all = await drafts(draft.owner);
  const used = all.reduce((n, d) => n + d.photos.reduce((s, p) => s + (p.blob?.size || 0), 0), 0);
  if (used + blob.size > 60 * 1024 * 1024) throw new Error(i18n.t("modules:mobile.storageLimit"));
  return { ...draft, updated: Date.now(), photos: [...draft.photos, { id: crypto.randomUUID(), itemId, name: "evidence.jpg", blob }] };
}
function upload(draft: Draft, photo: Photo, progress: (percent: number) => void): Promise<{id: number}> {
  return new Promise((resolve, reject) => {
    const form = new FormData(); form.append("key", photo.id); form.append("company_id", String(draft.owner.company_id));
    form.append("user_id", String(draft.owner.user_id)); form.append("entity_type", draft.kind === "inspection" ? "Inspection" : "VehicleAccident");
    form.append("entity_id", String(draft.serverId)); form.append("file", photo.blob!, photo.name);
    const xhr = new XMLHttpRequest(); xhr.open("POST", `${API_BASE_URL}/mobile/photos`); xhr.withCredentials = true; xhr.timeout = 60000;
    xhr.setRequestHeader("Accept-Language", getActiveLanguage());
    xhr.upload.onprogress = e => progress(e.lengthComputable ? Math.round(e.loaded / e.total * 100) : 0);
    xhr.onerror = xhr.ontimeout = () => reject(new SyncError(0, i18n.t("modules:mobile.network")));
    xhr.onload = () => {
      let data; try { data = JSON.parse(xhr.responseText); } catch { reject(new SyncError(xhr.status, i18n.t("modules:mobile.failed"))); return; }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new SyncError(xhr.status, data.message || i18n.t("modules:mobile.failed")));
    }; xhr.send(form);
  });
}
export async function synchronize(owner: Owner, progress: (id: string, percent: number) => void, manual = false) {
  if (!navigator.onLine) return;
  if (!navigator.locks) throw new Error(i18n.t("modules:mobile.unsupported"));
  await navigator.locks.request("vfc-mobile-sync", { ifAvailable: true }, async lock => {
    if (!lock) return;
    let current: CurrentUser;
    try { current = await mobileRequest<CurrentUser>("/auth/me"); }
    catch(error) { if(error instanceof SyncError && error.status === 401) throw new SyncError(401, i18n.t("modules:mobile.signIn")); throw error; }
    if (!sameOwner(owner, ownerOf(current)) || current.password_reset_required) throw new SyncError(401, i18n.t("modules:mobile.signIn"));
    for (let draft of await drafts(owner)) {
      if (!["Pending Sync", "Syncing", "Failed"].includes(draft.status) || (!manual && (draft.retryAt || 0) > Date.now())) continue;
      draft = { ...draft, status: "Syncing", error: undefined }; await saveDraft(draft);
      try {
        if (draft.kind === "accident" && !draft.serverId) {
          const value = await mobileRequest<{id: number}>("/mobile/sync", { ...owner, key: `${draft.id}:create`, kind: "accident", payload: draft.payload });
          draft.serverId = value.id; await saveDraft(draft);
        }
        for (let index = 0; index < draft.photos.length; index++) {
          const photo = draft.photos[index];
          if (!photo.attachmentId) {
            if (!photo.blob) throw new Error(i18n.t("modules:mobile.missingPhoto"));
            const result = await upload(draft, photo, n => progress(draft.id, Math.round((index + n / 100) / Math.max(1, draft.photos.length) * 90)));
            photo.attachmentId = result.id; delete photo.blob; await saveDraft(draft);
          }
        }
        if (draft.kind === "inspection") {
          const items = (draft.payload.items as Inspection["items"]).map(item => ({ ...item,
            photo_attachment_ids: Array.from(new Set([...(item.photo_attachment_ids || []), ...draft.photos.filter(p => p.itemId === item.id).map(p => p.attachmentId!)])) }));
          await mobileRequest("/mobile/sync", { ...owner, key: `${draft.id}:complete`, kind: "inspection", inspection_id: draft.serverId,
            expected_updated_at: draft.inspection!.updated_at, payload: { ...draft.payload, items } });
        }
        draft = { ...draft, status: "Synced", payload: {}, inspection: undefined, photos: [], updated: Date.now() };
        await saveDraft(draft); progress(draft.id, 100);
      } catch (error) {
        const status = error instanceof SyncError ? error.status : 0;
        draft.status = status === 409 ? "Conflict" : "Failed"; draft.attempts += 1;
        draft.retryAt = [400, 401, 403, 422].includes(status) ? Number.MAX_SAFE_INTEGER : Date.now() + Math.min(300000, 2000 * 2 ** Math.min(draft.attempts, 7));
        draft.error = status === 401 ? i18n.t("modules:mobile.signIn") : error instanceof Error ? error.message : i18n.t("modules:mobile.failed");
        await saveDraft(draft);
        if ([401, 403].includes(status)) throw error;
      }
    }
  });
}

export type AccidentPack = { owner: Owner; vehicle_id: number; driver_id: number; label: string };
export function saveAccidentPack(pack: AccidentPack) { localStorage.setItem(`vfc-mobile-pack-${pack.owner.company_id}-${pack.owner.user_id}`, JSON.stringify(pack)); }
export function accidentPack(owner: Owner): AccidentPack | null {
  try { const value = JSON.parse(localStorage.getItem(`vfc-mobile-pack-${owner.company_id}-${owner.user_id}`) || "null"); return value && sameOwner(owner, value.owner) ? value : null; } catch { return null; }
}
export async function newAccident(pack: AccidentPack) {
  await reserveLocal(pack.owner);
  const now = new Date();
  const draft: Draft = { id: crypto.randomUUID(), owner: pack.owner, kind: "accident", status: "Local Draft", photos: [], updated: Date.now(), attempts: 0, label: pack.label,
    payload: {vehicle_id: pack.vehicle_id, driver_id: pack.driver_id, accident_datetime: now.toISOString(),
      local_datetime: new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0,16),
      location: "", description: "", severity: "Minor", vehicle_available_after_accident: false} };
  await saveDraft(draft);
}

export async function downloadInspection(id: number, owner: Owner) {
  await reserveLocal(owner);
  const existing = (await drafts(owner)).find(d => d.kind === "inspection" && d.serverId === id && d.status !== "Synced");
  if (existing) return;
  const inspection = await mobileRequest<Inspection>(`/mobile/inspections/${id}`);
  if (inspection.completed_at || inspection.archived) throw new Error(i18n.t("errors:inspection_completed_locked"));
  await saveDraft(fromInspection(inspection, owner));
}
