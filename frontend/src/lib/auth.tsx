"use client";

import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { clearOffline, rememberOwner, ownerOf } from "@/lib/mobile/offline";
import { apiGet, apiPost, apiPut, clearAuthState } from "@/lib/api";
import {
  applyLanguage,
  getStoredLanguage,
  LANGUAGE_CHANGE_EVENT,
  LanguageCode,
  userLanguageSyncKey
} from "@/i18n/language";
import type { AuthResponse, CurrentUser } from "@/lib/types";

export const PERMISSIONS = {
  vehiclesWrite: "vehicles.edit",
  driversWrite: "drivers.manage",
  vehicleAssignmentsWrite: "assignments.manage",
  inspectionsCreate: "inspections.create",
  inspectionsWrite: "inspections.manage",
  workOrdersWrite: "maintenance.assign_work_order",
  papersWrite: "documents.verify",
  reservationsCreate: "reservations.create",
  reservationsApprove: "reservations.approve",
  servicesWrite: "maintenance.assign_work_order",
  fuelWrite: "fuel.create",
  accidentsWrite: "accidents.manage",
  claimsWrite: "claims.manage",
  reportsRead: "reports.view",
  importsWrite: "imports.manage"
} as const;

// Compatibility for sessions created before granular permissions were added.
// The API-provided list always wins when present; backend authorization remains authoritative.
const DEFAULT_ROLE_PERMISSIONS: Record<string, readonly string[]> = {
  admin: [
    "dashboard.view", "vehicles.view", "vehicles.create", "vehicles.edit", "vehicles.archive",
    "drivers.view", "drivers.manage", "assignments.view", "assignments.manage",
    "fuel.view", "fuel.create", "fuel.edit", "fuel.view_cost",
    "maintenance.view", "maintenance.create_work_order", "maintenance.assign_work_order", "maintenance.complete_work_order",
    "inspections.view", "inspections.create", "inspections.manage", "inspection_templates.manage",
    "documents.view", "documents.upload", "documents.verify",
    "reservations.view", "reservations.create", "reservations.approve",
    "reports.view", "reports.export", "accidents.view", "accidents.manage", "claims.manage",
    "imports.manage", "audit_logs.view", "users.manage", "roles.manage", "settings.manage"
  ],
  fleet_manager: [
    "dashboard.view", "vehicles.view", "vehicles.create", "vehicles.edit", "vehicles.archive",
    "drivers.view", "drivers.manage", "assignments.view", "assignments.manage",
    "fuel.view", "fuel.create", "fuel.edit", "fuel.view_cost",
    "maintenance.view", "maintenance.create_work_order", "maintenance.assign_work_order", "maintenance.complete_work_order",
    "inspections.view", "inspections.create", "inspections.manage", "inspection_templates.manage",
    "documents.view", "documents.upload", "documents.verify",
    "reservations.view", "reservations.create", "reservations.approve", "reports.view", "reports.export",
    "accidents.view", "accidents.manage", "claims.manage", "imports.manage", "audit_logs.view"
  ],
  mechanic: ["dashboard.view", "vehicles.view", "drivers.view", "assignments.view", "maintenance.view", "maintenance.create_work_order", "maintenance.assign_work_order", "maintenance.complete_work_order", "inspections.view", "inspections.create", "inspections.manage", "documents.view", "accidents.view"],
  driver: ["dashboard.view", "vehicles.view", "assignments.view", "fuel.view", "fuel.create", "maintenance.view", "inspections.view", "inspections.create", "documents.view", "documents.upload", "reservations.view", "reservations.create", "accidents.view"],
  finance: ["dashboard.view", "vehicles.view", "drivers.view", "fuel.view", "fuel.create", "fuel.edit", "fuel.view_cost", "maintenance.view", "documents.view", "reports.view", "reports.export", "accidents.view", "claims.manage"],
  viewer: ["dashboard.view", "vehicles.view", "drivers.view", "assignments.view", "fuel.view", "maintenance.view", "inspections.view", "documents.view", "reservations.view", "accidents.view"]
};

type PermissionKey = keyof typeof PERMISSIONS;

type AuthContextValue = {
  user: CurrentUser | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<CurrentUser>;
  registerFirstAdmin: (payload: { company_name: string; email: string; full_name: string; password: string }) => Promise<CurrentUser>;
  switchCompany: (companyId: number) => Promise<void>;
  logout: () => Promise<void>;
  can: (permission: PermissionKey | string) => boolean;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [ready, setReady] = useState(false);
  const generation = useRef(0);

  useEffect(() => {
    if (!user) return;
    const saveLanguage = (event: Event) => {
      const language = (event as CustomEvent<LanguageCode>).detail;
      void apiPut("/auth/me/language", { language }).catch(() => { /* Local preference is retained. */ });
    };
    window.addEventListener("language:save", saveLanguage);
    return () => window.removeEventListener("language:save", saveLanguage);
  }, [user]);

  async function reconcileLanguage(current: CurrentUser): Promise<CurrentUser> {
    if (current.preferred_language !== "sq" && current.preferred_language !== "en") {
      current = { ...current, preferred_language: "en" };
    }
    const local = getStoredLanguage();
    const syncKey = userLanguageSyncKey(current.id);
    const firstSync = typeof window !== "undefined" && !window.localStorage.getItem(syncKey);
    if (firstSync && local === "sq" && current.preferred_language === "en") {
      const saved = await apiPut<{ preferred_language: LanguageCode }>("/auth/me/language", { language: "sq" });
      current = { ...current, preferred_language: saved.preferred_language };
    }
    if (typeof window !== "undefined") window.localStorage.setItem(syncKey, "1");
    applyLanguage(current.preferred_language);
    return current;
  }

  useEffect(() => {
    let active = true;
    // One-time cleanup of the previous browser-readable credential. Never read it.
    window.localStorage.removeItem("vehicle_fleet_control_token");
    async function loadCurrentUser() {
      const currentGeneration = generation.current;
      try {
        const current = await reconcileLanguage(await apiGet<CurrentUser>("/auth/me"));
        if (active && currentGeneration === generation.current) { rememberOwner(ownerOf(current)); setUser(current); }
      } catch {
        if (active && currentGeneration === generation.current) setUser(null);
      } finally {
        if (active && currentGeneration === generation.current) setReady(true);
      }
    }

    function handleLogout() {
      generation.current += 1;
      setUser(null);
      setReady(true);
    }

    function handleLanguage(event: Event) {
      const language = (event as CustomEvent<LanguageCode>).detail;
      setUser((current) => current ? { ...current, preferred_language: language } : current);
    }

    window.addEventListener("auth:logout", handleLogout);
    window.addEventListener(LANGUAGE_CHANGE_EVENT, handleLanguage);
    const scopeChanged = (event: StorageEvent) => {
      if (event.key === "vfc-mobile-owner") { setUser(null); void loadCurrentUser(); }
    };
    window.addEventListener("storage", scopeChanged);
    window.addEventListener("online", loadCurrentUser);
    void loadCurrentUser();
    return () => {
      active = false;
      window.removeEventListener("online", loadCurrentUser);
      window.removeEventListener("storage", scopeChanged);
      window.removeEventListener("auth:logout", handleLogout);
      window.removeEventListener(LANGUAGE_CHANGE_EVENT, handleLanguage);
    };
  }, []);

  const value = useMemo<AuthContextValue>(() => ({
    user,
    ready,
    async login(email: string, password: string) {
      generation.current += 1;
      const result = await apiPost<AuthResponse>("/auth/login", { email, password });
      const current = await reconcileLanguage(result.user);
      rememberOwner(ownerOf(current));
      setUser(current);
      setReady(true);
      return current;
    },
    async registerFirstAdmin(payload: { company_name: string; email: string; full_name: string; password: string }) {
      const result = await apiPost<AuthResponse>("/auth/register", payload);
      const current = await reconcileLanguage(result.user);
      rememberOwner(ownerOf(current));
      setUser(current);
      setReady(true);
      return current;
    },
    async switchCompany(companyId: number) {
      await apiPost<AuthResponse>("/auth/switch-company", { company_id: companyId });
      localStorage.removeItem("vfc-mobile-owner");
      // Discard page state and outstanding requests from the previous tenant.
      window.location.assign("/dashboard");
    },
    async logout() {
      await apiPost<void>("/auth/logout", {});
      try { await clearOffline(); }
      finally {
        clearAuthState();
        setUser(null);
        setReady(true);
      }
    },
    can(permission: PermissionKey | string) {
      if (!user) return false;
      const code = permission in PERMISSIONS ? PERMISSIONS[permission as PermissionKey] : permission;
      const granted = Array.isArray(user.permissions)
        ? user.permissions
        : DEFAULT_ROLE_PERMISSIONS[user.role] ?? [];
      return granted.includes(code);
    }
  }), [ready, user]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider.");
  }
  return context;
}
