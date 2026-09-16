"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiGet, apiPost, apiPut } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import type { CurrentUser, Driver, MasterDataItem, Role, ScopeAssignment } from "@/lib/types";

type UserForm = {
  email: string; full_name: string; password: string; role_id: number | null; is_active: boolean;
  require_password_change: boolean;
  preferred_language: "en" | "sq"; driver_id: number | null; location_id: number | null;
  department_id: number | null; cost_center_id: number | null; own_records_only: boolean;
};

const emptyForm: UserForm = { email: "", full_name: "", password: "", role_id: null, is_active: true, require_password_change: true, preferred_language: "en", driver_id: null, location_id: null, department_id: null, cost_center_id: null, own_records_only: false };

export default function AdminUsersPage() {
  const { t } = useTranslation(["modules", "common"]);
  const { can } = useAuth();
  const { formatDateTime } = useLanguage();
  const [users, setUsers] = useState<CurrentUser[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [drivers, setDrivers] = useState<Driver[]>([]);
  const [locations, setLocations] = useState<MasterDataItem[]>([]);
  const [departments, setDepartments] = useState<MasterDataItem[]>([]);
  const [costCenters, setCostCenters] = useState<MasterDataItem[]>([]);
  const [editing, setEditing] = useState<CurrentUser | null>(null);
  const [form, setForm] = useState<UserForm>(emptyForm);
  const [temporaryPassword, setTemporaryPassword] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const showError = useCallback((reason: unknown) => { setError(reason instanceof Error ? reason.message : t("modules:admin.requestFailed")); }, [t]);

  const load = useCallback(async () => {
    setError("");
    try {
      const [userRows, roleRows] = await Promise.all([apiGet<CurrentUser[]>("/admin/users"), apiGet<Role[]>("/admin/roles")]);
      setUsers(userRows); setRoles(roleRows.filter((role) => role.is_active));
      const optional = await Promise.allSettled([
        apiGet<Driver[]>("/drivers"), apiGet<MasterDataItem[]>("/admin/locations"),
        apiGet<MasterDataItem[]>("/admin/departments"), apiGet<MasterDataItem[]>("/admin/cost-centers")
      ]);
      if (optional[0].status === "fulfilled") setDrivers(optional[0].value);
      if (optional[1].status === "fulfilled") setLocations(optional[1].value);
      if (optional[2].status === "fulfilled") setDepartments(optional[2].value);
      if (optional[3].status === "fulfilled") setCostCenters(optional[3].value);
    } catch (reason) { showError(reason); }
  }, [showError]);

  useEffect(() => { if (can("users.manage")) void load(); }, [can, load]);

  const roleName = useMemo(() => Object.fromEntries(roles.map((role) => [role.code, role.name])), [roles]);

  function startEdit(user: CurrentUser) {
    const scope = user.role_assignments?.[0];
    setEditing(user);
    setForm({ email: user.email, full_name: user.full_name, password: "", role_id: scope?.role_id ?? roles.find((role) => role.code === user.role)?.id ?? null, is_active: user.is_active, require_password_change: user.password_reset_required ?? false, preferred_language: user.preferred_language, driver_id: user.driver_id ?? null, location_id: scope?.location_id ?? null, department_id: scope?.department_id ?? null, cost_center_id: scope?.cost_center_id ?? null, own_records_only: scope?.own_records_only ?? false });
    setTemporaryPassword(""); setMessage("");
  }

  function payload() {
    const assignment: ScopeAssignment = { role_id: form.role_id!, location_id: form.location_id, department_id: form.department_id, cost_center_id: form.cost_center_id, own_records_only: form.own_records_only };
    return { email: form.email, full_name: form.full_name, is_active: form.is_active, preferred_language: form.preferred_language, driver_id: form.driver_id, role_assignments: [assignment] };
  }

  async function save(event: FormEvent) {
    event.preventDefault(); setMessage(""); setError("");
    if (!form.role_id) return;
    try {
      if (editing) await apiPut(`/admin/users/${editing.id}`, payload());
      else await apiPost("/admin/users", { ...payload(), password: form.password, require_password_change: form.require_password_change });
      setEditing(null); setForm(emptyForm); setMessage(t("modules:admin.saved")); await load();
    } catch (reason) { showError(reason); }
  }

  async function resetPassword() {
    if (!editing) return;
    if (temporaryPassword.length < 12) { setError(t("modules:admin.passwordMinimum")); return; }
    setError("");
    try {
      await apiPost(`/admin/users/${editing.id}/reset-password`, { temporary_password: temporaryPassword, require_change: true });
      setTemporaryPassword(""); setMessage(t("modules:admin.passwordReset")); await load();
    } catch (reason) { showError(reason); }
  }

  async function revokeSessions() {
    if (!editing) return;
    setError("");
    try {
      await apiPost(`/admin/users/${editing.id}/revoke-sessions`, {});
      setMessage(t("modules:admin.sessionsRevoked"));
    } catch (reason) { showError(reason); }
  }

  if (!can("users.manage")) return <div className="card">{t("modules:admin.noAccess")}</div>;
  return <div>
    <div className="header"><div><h1>{t("modules:admin.usersTitle")}</h1><p className="muted">{t("modules:admin.usersDescription")}</p></div><button className="button" onClick={() => { setEditing(null); setForm({ ...emptyForm, role_id: roles[0]?.id ?? null }); }}>{t("modules:admin.createUser")}</button></div>
    {message && <div className="successBanner">{message}</div>}
    {error && <div className="error spaced" role="alert">{error}</div>}
    <div className="card tableScroll"><table className="table"><thead><tr><th>{t("modules:admin.user")}</th><th>{t("modules:admin.role")}</th><th>{t("modules:admin.status")}</th><th>{t("modules:admin.lastLogin")}</th><th /></tr></thead><tbody>{users.map((user) => <tr key={user.id}><td><strong>{user.full_name}</strong><div className="muted">{user.email}</div></td><td>{user.roles.map((role) => roleName[role] ?? role).join(", ")}</td><td><span className={user.is_active ? "successBadge" : "dangerBadge"}>{user.is_active ? t("modules:admin.active") : t("modules:admin.inactive")}</span></td><td>{user.last_login_at ? formatDateTime(user.last_login_at) : t("modules:admin.never")}</td><td><button className="secondaryButton smallButton" onClick={() => startEdit(user)}>{t("common:actions.edit")}</button></td></tr>)}</tbody></table></div>
    <form className="card formGrid" onSubmit={save}>
      <h2>{editing ? t("modules:admin.editUser") : t("modules:admin.createUser")}</h2>
      <label>{t("modules:admin.fullName")}<input className="input" required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></label>
      <label>{t("modules:admin.email")}<input className="input" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
      {!editing && <label>{t("modules:admin.password")}<input className="input" type="password" aria-label={t("modules:admin.password")} autoComplete="new-password" minLength={12} required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /><span className="muted">{t("modules:admin.passwordMinimum")}</span></label>}
      {!editing && <label className="checkboxLabel"><input type="checkbox" checked={form.require_password_change} onChange={(e) => setForm({ ...form, require_password_change: e.target.checked })} />{t("modules:admin.requirePasswordChange")}</label>}
      <label>{t("modules:admin.role")}<select className="input" aria-label={t("modules:admin.role")} required value={form.role_id ?? ""} onChange={(e) => setForm({ ...form, role_id: Number(e.target.value) || null })}><option value="">—</option>{roles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}</select></label>
      <label>{t("modules:admin.language")}<select className="input" value={form.preferred_language} onChange={(e) => setForm({ ...form, preferred_language: e.target.value as "en" | "sq" })}><option value="en">English</option><option value="sq">Shqip</option></select></label>
      <label>{t("modules:admin.driverProfile")}<select className="input" value={form.driver_id ?? ""} onChange={(e) => setForm({ ...form, driver_id: e.target.value ? Number(e.target.value) : null })}><option value="">-</option>{drivers.map((driver) => <option key={driver.id} value={driver.id}>{driver.full_name}</option>)}</select></label>
      <label>{t("modules:admin.locationScope")}<select className="input" value={form.location_id ?? ""} onChange={(e) => setForm({ ...form, location_id: e.target.value ? Number(e.target.value) : null })}><option value="">{t("modules:admin.all")}</option>{locations.filter((x) => x.is_active).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
      <label>{t("modules:admin.departmentScope")}<select className="input" value={form.department_id ?? ""} onChange={(e) => setForm({ ...form, department_id: e.target.value ? Number(e.target.value) : null })}><option value="">{t("modules:admin.all")}</option>{departments.filter((x) => x.is_active).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
      <label>{t("modules:admin.costCenterScope")}<select className="input" value={form.cost_center_id ?? ""} onChange={(e) => setForm({ ...form, cost_center_id: e.target.value ? Number(e.target.value) : null })}><option value="">{t("modules:admin.all")}</option>{costCenters.filter((x) => x.is_active).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
      <label className="checkboxLabel"><input type="checkbox" checked={form.own_records_only} onChange={(e) => setForm({ ...form, own_records_only: e.target.checked })} />{t("modules:admin.ownRecordsOnly")}</label>
      <label className="checkboxLabel"><input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />{t("modules:admin.active")}</label>
      <div className="actions"><button className="button" type="submit">{t("common:actions.save")}</button>{editing && <button className="secondaryButton" type="button" onClick={revokeSessions}>{t("modules:admin.forceLogout")}</button>}</div>
      {editing && <div className="formRow"><label>{t("modules:admin.temporaryPassword")}<input className="input" type="password" aria-label={t("modules:admin.temporaryPassword")} autoComplete="new-password" minLength={12} value={temporaryPassword} onChange={(e) => setTemporaryPassword(e.target.value)} /><span className="muted">{t("modules:admin.passwordMinimum")}</span></label><button className="secondaryButton" type="button" onClick={resetPassword}>{t("modules:admin.resetPassword")}</button></div>}
    </form>
  </div>;
}
