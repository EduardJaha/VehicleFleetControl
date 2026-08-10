"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiGet, apiPost, apiPut } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Permission, Role } from "@/lib/types";

export default function AdminRolesPage() {
  const { t } = useTranslation(["modules", "common"]);
  const { can } = useAuth();
  const [roles, setRoles] = useState<Role[]>([]);
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [editing, setEditing] = useState<Role | null>(null);
  const [code, setCode] = useState(""); const [name, setName] = useState("");
  const [description, setDescription] = useState(""); const [active, setActive] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");

  const showError = useCallback((reason: unknown) => { setError(reason instanceof Error ? reason.message : t("modules:admin.requestFailed")); }, [t]);

  const load = useCallback(async () => {
    setError("");
    try {
      const [roleRows, permissionRows] = await Promise.all([apiGet<Role[]>("/admin/roles"), apiGet<Permission[]>("/admin/permissions")]);
      setRoles(roleRows); setPermissions(permissionRows);
    } catch (reason) { showError(reason); }
  }, [showError]);
  useEffect(() => { if (can("roles.manage")) void load(); }, [can, load]);
  const modules = useMemo(() => Object.entries(permissions.reduce<Record<string, Permission[]>>((groups, permission) => {
    (groups[permission.module] ??= []).push(permission); return groups;
  }, {})), [permissions]);

  function choose(role?: Role) {
    setEditing(role ?? null); setCode(role?.code ?? ""); setName(role?.name ?? "");
    setDescription(role?.description ?? ""); setActive(role?.is_active ?? true); setSelected(new Set(role?.permissions ?? []));
  }
  function toggle(permission: string) {
    const next = new Set(selected); next.has(permission) ? next.delete(permission) : next.add(permission); setSelected(next);
  }
  async function save(event: FormEvent) {
    event.preventDefault(); setError("");
    try {
      const payload = { code, name, description: description || null, is_active: active, permission_codes: Array.from(selected) };
      if (editing) await apiPut(`/admin/roles/${editing.id}`, payload);
      else await apiPost("/admin/roles", payload);
      choose(); await load();
    } catch (reason) { showError(reason); }
  }
  if (!can("roles.manage")) return <div className="card">{t("modules:admin.noAccess")}</div>;
  return <div>
    <div className="header"><div><h1>{t("modules:admin.rolesTitle")}</h1><p className="muted">{t("modules:admin.rolesDescription")}</p></div><button className="button" onClick={() => choose()}>{t("modules:admin.createRole")}</button></div>
    {error && <div className="error spaced" role="alert">{error}</div>}
    <div className="grid cols-2"><div className="card"><h2>{t("modules:admin.roles")}</h2>{roles.map((role) => <button key={role.id} className="recordRow adminRoleRow" onClick={() => choose(role)}><span><strong>{role.name}</strong><span className="muted">{role.code} · {t("modules:admin.userCount", { count: role.user_count })}</span></span><span className={role.is_active ? "successBadge" : "dangerBadge"}>{role.is_active ? t("modules:admin.active") : t("modules:admin.inactive")}</span></button>)}</div>
      <form className="card" onSubmit={save}><h2>{editing ? t("modules:admin.editRole") : t("modules:admin.createRole")}</h2>
        <div className="formGrid"><label>{t("modules:admin.roleCode")}<input className="input" required pattern="[a-z][a-z0-9_]*" disabled={Boolean(editing)} value={code} onChange={(e) => setCode(e.target.value)} /></label><label>{t("modules:admin.roleName")}<input className="input" required value={name} onChange={(e) => setName(e.target.value)} /></label><label>{t("modules:admin.description")}<textarea className="input" value={description} onChange={(e) => setDescription(e.target.value)} /></label><label className="checkboxLabel"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />{t("modules:admin.active")}</label></div>
        <h3>{t("modules:admin.permissions")}</h3>{modules.map(([module, rows]) => <fieldset className="permissionGroup" key={module}><legend>{module}</legend>{rows?.map((permission) => <label className="checkboxLabel" key={permission.code}><input type="checkbox" checked={selected.has(permission.code)} onChange={() => toggle(permission.code)} /><span><strong>{permission.code}</strong><span className="muted">{permission.description}</span></span></label>)}</fieldset>)}
        <button className="button" type="submit">{t("common:actions.save")}</button>
      </form></div>
  </div>;
}
