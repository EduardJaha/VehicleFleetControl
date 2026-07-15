"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, clearAuthToken, getAuthToken, setAuthToken } from "@/lib/api";
import type { AuthResponse, CurrentUser, UserRole } from "@/lib/types";

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: "Admin",
  fleet_manager: "Fleet Manager",
  mechanic: "Mechanic",
  driver: "Driver",
  finance: "Finance",
  viewer: "Viewer"
};

export const PERMISSIONS = {
  vehiclesWrite: ["admin", "fleet_manager"],
  driversWrite: ["admin", "fleet_manager"],
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

  useEffect(() => {
    let active = true;
    async function loadCurrentUser() {
      const token = getAuthToken();
      if (!token) {
        setReady(true);
        return;
      }
      try {
        const current = await apiGet<CurrentUser>("/auth/me");
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

    window.addEventListener("auth:logout", handleLogout);
    void loadCurrentUser();
    return () => {
      active = false;
      window.removeEventListener("auth:logout", handleLogout);
    };
  }, []);

  const value = useMemo<AuthContextValue>(() => ({
    user,
    ready,
    async login(email: string, password: string) {
      const result = await apiPost<AuthResponse>("/auth/login", { email, password });
      setAuthToken(result.access_token);
      setUser(result.user);
      setReady(true);
    },
    async registerFirstAdmin(payload: { email: string; full_name: string; password: string }) {
      const result = await apiPost<AuthResponse>("/auth/register", payload);
      setAuthToken(result.access_token);
      setUser(result.user);
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
