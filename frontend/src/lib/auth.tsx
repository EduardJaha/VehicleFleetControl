"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, apiPut, clearAuthToken, getAuthToken, setAuthToken } from "@/lib/api";
import {
  applyLanguage,
  getStoredLanguage,
  LANGUAGE_CHANGE_EVENT,
  LanguageCode,
  userLanguageSyncKey
} from "@/i18n/language";
import type { AuthResponse, CurrentUser, UserRole } from "@/lib/types";

export const PERMISSIONS = {
  vehiclesWrite: ["admin", "fleet_manager"],
  driversWrite: ["admin", "fleet_manager"],
  vehicleAssignmentsWrite: ["admin", "fleet_manager"],
  inspectionsCreate: ["admin", "fleet_manager", "mechanic", "driver"],
  inspectionsWrite: ["admin", "fleet_manager", "mechanic"],
  workOrdersWrite: ["admin", "fleet_manager", "mechanic"],
  papersWrite: ["admin", "fleet_manager"],
  reservationsCreate: ["admin", "fleet_manager", "driver"],
  reservationsApprove: ["admin", "fleet_manager"],
  servicesWrite: ["admin", "fleet_manager", "mechanic"],
  fuelWrite: ["admin", "finance"],
  accidentsWrite: ["admin", "fleet_manager"],
  reportsRead: ["admin", "fleet_manager", "finance"]
} as const satisfies Record<string, readonly UserRole[]>;

type PermissionKey = keyof typeof PERMISSIONS;

type AuthContextValue = {
  user: CurrentUser | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  registerFirstAdmin: (payload: { email: string; full_name: string; password: string }) => Promise<void>;
  logout: () => void;
  can: (permission: PermissionKey) => boolean;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [ready, setReady] = useState(false);

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
    async function loadCurrentUser() {
      const token = getAuthToken();
      if (!token) {
        setReady(true);
        return;
      }
      try {
        const current = await reconcileLanguage(await apiGet<CurrentUser>("/auth/me"));
        if (active) setUser(current);
      } catch {
        if (active) setUser(null);
      } finally {
        if (active) setReady(true);
      }
    }

    function handleLogout() {
      setUser(null);
      setReady(true);
    }

    function handleLanguage(event: Event) {
      const language = (event as CustomEvent<LanguageCode>).detail;
      setUser((current) => current ? { ...current, preferred_language: language } : current);
    }

    window.addEventListener("auth:logout", handleLogout);
    window.addEventListener(LANGUAGE_CHANGE_EVENT, handleLanguage);
    void loadCurrentUser();
    return () => {
      active = false;
      window.removeEventListener("auth:logout", handleLogout);
      window.removeEventListener(LANGUAGE_CHANGE_EVENT, handleLanguage);
    };
  }, []);

  const value = useMemo<AuthContextValue>(() => ({
    user,
    ready,
    async login(email: string, password: string) {
      const result = await apiPost<AuthResponse>("/auth/login", { email, password });
      setAuthToken(result.access_token);
      setUser(await reconcileLanguage(result.user));
      setReady(true);
    },
    async registerFirstAdmin(payload: { email: string; full_name: string; password: string }) {
      const result = await apiPost<AuthResponse>("/auth/register", payload);
      setAuthToken(result.access_token);
      setUser(await reconcileLanguage(result.user));
      setReady(true);
    },
    logout() {
      clearAuthToken();
      setUser(null);
      setReady(true);
    },
    can(permission: PermissionKey) {
      return !!user && (PERMISSIONS[permission] as readonly UserRole[]).includes(user.role);
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
