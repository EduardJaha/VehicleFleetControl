"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiGet, apiPost, apiPut } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { MasterDataItem } from "@/lib/types";

const kinds = ["locations", "departments", "cost-centers"] as const;
type Kind = typeof kinds[number];

export default function AdminSettingsPage() {
  const { t } = useTranslation(["modules", "common"]); const { can } = useAuth();
  const [kind, setKind] = useState<Kind>("locations"); const [rows, setRows] = useState<MasterDataItem[]>([]);
  const [editing, setEditing] = useState<MasterDataItem | null>(null); const [code, setCode] = useState("");
  const [name, setName] = useState(""); const [active, setActive] = useState(true);
  const [error, setError] = useState("");
  const showError = useCallback((reason: unknown) => { setError(reason instanceof Error ? reason.message : t("modules:admin.requestFailed")); }, [t]);
  const load = useCallback(async (selected = kind) => {
    setError("");
    try { setRows(await apiGet<MasterDataItem[]>(`/admin/${selected}`)); }
    catch (reason) { showError(reason); }
  }, [kind, showError]);
  useEffect(() => {
    if (can("settings.manage")) void load(kind);
  }, [kind, can, load]);
  function choose(row?: MasterDataItem) { setEditing(row ?? null); setCode(row?.code ?? ""); setName(row?.name ?? ""); setActive(row?.is_active ?? true); }
  async function save(event: FormEvent) {
    event.preventDefault(); setError("");
    try {
      const payload = { code, name, is_active: active };
      if (editing) await apiPut(`/admin/${kind}/${editing.id}`, payload); else await apiPost(`/admin/${kind}`, { code, name });
      choose(); await load();
    } catch (reason) { showError(reason); }
  }
  if (!can("settings.manage")) return <div className="card">{t("modules:admin.noAccess")}</div>;
  return <div><div className="header"><div><h1>{t("modules:admin.settingsTitle")}</h1><p className="muted">{t("modules:admin.settingsDescription")}</p></div></div>
    {error && <div className="error spaced" role="alert">{error}</div>}
    <div className="maintenanceTabs">{kinds.map((item) => <button key={item} className={item === kind ? "maintenanceTab active" : "maintenanceTab"} onClick={() => { setKind(item); choose(); }}>{t(`modules:admin.${item.replace("-", "")}`)}</button>)}</div>
    <div className="grid cols-2"><div className="card"><div className="recordTitle"><h2>{t(`modules:admin.${kind.replace("-", "")}`)}</h2><button className="button smallButton" onClick={() => choose()}>{t("common:actions.add")}</button></div>{rows.map((row) => <button className="recordRow adminRoleRow" key={row.id} onClick={() => choose(row)}><span><strong>{row.name}</strong><span className="muted">{row.code}</span></span><span className={row.is_active ? "successBadge" : "dangerBadge"}>{row.is_active ? t("modules:admin.active") : t("modules:admin.inactive")}</span></button>)}</div>
      <form className="card formGrid" onSubmit={save}><h2>{editing ? t("modules:admin.editSetting") : t("modules:admin.createSetting")}</h2><label>{t("modules:admin.code")}<input className="input" required value={code} onChange={(e) => setCode(e.target.value)} /></label><label>{t("modules:admin.name")}<input className="input" required value={name} onChange={(e) => setName(e.target.value)} /></label>{editing && <label className="checkboxLabel"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />{t("modules:admin.active")}</label>}<button className="button" type="submit">{t("common:actions.save")}</button></form>
    </div></div>;
}
