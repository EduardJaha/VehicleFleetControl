"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Image from "next/image";
import { useTranslation } from "react-i18next";
import { apiGet, apiGetBlob, apiPost, apiPostForm, apiPut } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { CompanySettings, MasterDataItem } from "@/lib/types";

const kinds = ["locations", "departments", "cost-centers"] as const;
const notificationRules = ["service_reminders", "document_expiry", "driver_license_expiry", "overdue_assignments"] as const;
type Kind = typeof kinds[number];

function copyCompany(company: CompanySettings): CompanySettings {
  return { ...company, notification_rules: { ...company.notification_rules } };
}

function companyInitials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase() || "CO";
}

function EditIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z" /></svg>;
}

export default function AdminSettingsPage() {
  const { t } = useTranslation(["modules", "common"]);
  const { can } = useAuth();
  const [kind, setKind] = useState<Kind>("locations");
  const [rows, setRows] = useState<MasterDataItem[]>([]);
  const [editing, setEditing] = useState<MasterDataItem | null>(null);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [active, setActive] = useState(true);
  const [error, setError] = useState("");
  const [company, setCompany] = useState<CompanySettings | null>(null);
  const [companyDraft, setCompanyDraft] = useState<CompanySettings | null>(null);
  const [editingCompany, setEditingCompany] = useState(false);
  const [savingCompany, setSavingCompany] = useState(false);
  const [companySaved, setCompanySaved] = useState(false);
  const [selectedLogo, setSelectedLogo] = useState<File | null>(null);
  const [savedLogoUrl, setSavedLogoUrl] = useState<string | null>(null);
  const [selectedLogoUrl, setSelectedLogoUrl] = useState<string | null>(null);

  const showError = useCallback((reason: unknown) => {
    setError(reason instanceof Error ? reason.message : t("modules:admin.requestFailed"));
  }, [t]);

  const loadLogo = useCallback(async (settings: CompanySettings) => {
    if (!settings.logo_path) {
      setSavedLogoUrl(null);
      return;
    }
    try {
      const blob = await apiGetBlob("/admin/company-settings/logo");
      setSavedLogoUrl(URL.createObjectURL(blob));
    } catch {
      setSavedLogoUrl(null);
    }
  }, []);

  const load = useCallback(async (selected = kind) => {
    setError("");
    try {
      setRows(await apiGet<MasterDataItem[]>(`/admin/${selected}`));
    } catch (reason) {
      showError(reason);
    }
  }, [kind, showError]);

  useEffect(() => {
    if (!can("settings.manage")) return;
    void load(kind);
    void apiGet<CompanySettings>("/admin/company-settings").then((settings) => {
      setCompany(settings);
      setCompanyDraft(copyCompany(settings));
      void loadLogo(settings);
    }).catch(showError);
  }, [kind, can, load, loadLogo, showError]);

  useEffect(() => () => {
    if (savedLogoUrl) URL.revokeObjectURL(savedLogoUrl);
  }, [savedLogoUrl]);

  useEffect(() => () => {
    if (selectedLogoUrl) URL.revokeObjectURL(selectedLogoUrl);
  }, [selectedLogoUrl]);

  function choose(row?: MasterDataItem) {
    setEditing(row ?? null);
    setCode(row?.code ?? "");
    setName(row?.name ?? "");
    setActive(row?.is_active ?? true);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const payload = { code, name, is_active: active };
      if (editing) await apiPut(`/admin/${kind}/${editing.id}`, payload);
      else await apiPost(`/admin/${kind}`, { code, name });
      choose();
      await load();
    } catch (reason) {
      showError(reason);
    }
  }

  function beginCompanyEdit() {
    if (!company) return;
    setCompanyDraft(copyCompany(company));
    setSelectedLogo(null);
    setSelectedLogoUrl(null);
    setCompanySaved(false);
    setEditingCompany(true);
  }

  function cancelCompanyEdit() {
    if (company) setCompanyDraft(copyCompany(company));
    setSelectedLogo(null);
    setSelectedLogoUrl(null);
    setEditingCompany(false);
  }

  function selectLogo(file?: File) {
    if (!file) return;
    setSelectedLogo(file);
    setSelectedLogoUrl(URL.createObjectURL(file));
  }

  async function saveCompany(event: FormEvent) {
    event.preventDefault();
    if (!companyDraft) return;
    setError("");
    setCompanySaved(false);
    setSavingCompany(true);
    try {
      let saved = await apiPut<CompanySettings>("/admin/company-settings", companyDraft);
      if (selectedLogo) {
        const body = new FormData();
        body.append("file", selectedLogo);
        saved = await apiPostForm<CompanySettings>("/admin/company-settings/logo", body);
      }
      setCompany(saved);
      setCompanyDraft(copyCompany(saved));
      setSelectedLogo(null);
      setSelectedLogoUrl(null);
      setCompanySaved(true);
      setEditingCompany(false);
      await loadLogo(saved);
    } catch (reason) {
      showError(reason);
    } finally {
      setSavingCompany(false);
    }
  }

  if (!can("settings.manage")) return <div className="card">{t("modules:admin.noAccess")}</div>;

  const visibleLogo = selectedLogoUrl ?? savedLogoUrl;
  const languageLabel = company?.default_language === "sq" ? "Shqip" : "English";

  return <div className="companySettingsPage">
    <div className="header companySettingsHeader">
      <div><h1>{t("modules:admin.settingsTitle")}</h1><p className="muted">{t("modules:admin.settingsDescription")}</p></div>
    </div>
    {error && <div className="error spaced" role="alert">{error}</div>}
    {companySaved && <div className="successBanner" role="status">{t("modules:admin.settingsSaved")}</div>}

    {company && !editingCompany && <section className="card companyProfileCard spaced" aria-labelledby="company-profile-title">
      <div className="companyProfileTop">
        <div className="companyIdentity">
          <div className="companyLogo" aria-hidden={!visibleLogo}>
            {visibleLogo ? <Image src={visibleLogo} alt={t("modules:admin.companyLogoAlt", { name: company.company_name })} width={110} height={110} unoptimized /> : <span>{companyInitials(company.company_name)}</span>}
          </div>
          <div>
            <div className="companyEyebrow">{t("modules:admin.companyProfile")}</div>
            <h2 id="company-profile-title">{company.company_name}</h2>
            <p className="muted">{t("modules:admin.companyId", { id: company.company_id })}</p>
          </div>
        </div>
        <button className="secondaryButton companyEditButton" type="button" onClick={beginCompanyEdit}><EditIcon />{t("modules:admin.editCompany")}</button>
      </div>

      <div className="companyProfileDivider" />
      <div className="companyInfoGrid">
        <div className="companyInfoItem companyAddressItem"><span>{t("modules:admin.address")}</span><strong>{company.address || t("common:states.notAvailable")}</strong></div>
        <div className="companyInfoItem"><span>{t("modules:admin.defaultLanguage")}</span><strong>{languageLabel}</strong></div>
        <div className="companyInfoItem"><span>{t("modules:admin.timezone")}</span><strong>{company.timezone}</strong></div>
        <div className="companyInfoItem"><span>{t("modules:admin.currency")}</span><strong>{company.currency}</strong></div>
      </div>

      <div className="companyNotificationSummary">
        <div><h3>{t("modules:admin.notificationRules")}</h3><p className="muted">{t("modules:admin.notificationRulesDescription")}</p></div>
        <div className="notificationRuleList">{notificationRules.map((rule) => {
          const enabled = company.notification_rules[rule] !== false;
          return <span className={enabled ? "notificationRule enabled" : "notificationRule"} key={rule}><i />{t(`modules:admin.${rule}`)}<small>{enabled ? t("modules:admin.enabled") : t("modules:admin.disabled")}</small></span>;
        })}</div>
      </div>
    </section>}

    {companyDraft && editingCompany && <form className="card companyEditCard spaced" onSubmit={saveCompany}>
      <div className="companyEditHeading"><div><h2>{t("modules:admin.editCompany")}</h2><p className="muted">{t("modules:admin.editCompanyDescription")}</p></div></div>
      <div className="companyEditLayout">
        <div className="companyLogoEditor">
          <div className="companyLogo editing">{visibleLogo ? <Image src={visibleLogo} alt="" width={110} height={110} unoptimized /> : <span>{companyInitials(companyDraft.company_name)}</span>}</div>
          <label className="secondaryButton logoUploadButton">{t("modules:admin.changeLogo")}<input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => selectLogo(event.target.files?.[0])} /></label>
          <small className="muted">{t("modules:admin.logoHelp")}</small>
        </div>
        <div className="companyEditFields">
          <label>{t("modules:admin.companyName")}<input className="input" required value={companyDraft.company_name} onChange={(event) => setCompanyDraft({ ...companyDraft, company_name: event.target.value })} /></label>
          <label className="companyAddressField">{t("modules:admin.address")}<textarea className="input textarea" value={companyDraft.address ?? ""} onChange={(event) => setCompanyDraft({ ...companyDraft, address: event.target.value })} /></label>
          <label>{t("modules:admin.defaultLanguage")}<select className="input" value={companyDraft.default_language} onChange={(event) => setCompanyDraft({ ...companyDraft, default_language: event.target.value as "en" | "sq" })}><option value="en">English</option><option value="sq">Shqip</option></select></label>
          <label>{t("modules:admin.timezone")}<input className="input" required value={companyDraft.timezone} onChange={(event) => setCompanyDraft({ ...companyDraft, timezone: event.target.value })} placeholder="Europe/Belgrade" /></label>
          <label>{t("modules:admin.currency")}<input className="input" required minLength={3} maxLength={3} value={companyDraft.currency} onChange={(event) => setCompanyDraft({ ...companyDraft, currency: event.target.value.toUpperCase() })} placeholder="EUR" /></label>
        </div>
      </div>
      <fieldset className="companyNotificationEditor"><legend>{t("modules:admin.notificationRules")}</legend><p className="muted">{t("modules:admin.notificationRulesDescription")}</p><div className="notificationCheckboxGrid">{notificationRules.map((rule) => <label className="notificationCheckbox" key={rule}><input type="checkbox" checked={companyDraft.notification_rules[rule] !== false} onChange={(event) => setCompanyDraft({ ...companyDraft, notification_rules: { ...companyDraft.notification_rules, [rule]: event.target.checked } })} /><span><strong>{t(`modules:admin.${rule}`)}</strong><small>{t(`modules:admin.${rule}Help`)}</small></span></label>)}</div></fieldset>
      <div className="companyEditActions"><button className="secondaryButton" type="button" disabled={savingCompany} onClick={cancelCompanyEdit}>{t("common:actions.cancel")}</button><button className="button" type="submit" disabled={savingCompany}>{savingCompany ? t("common:states.saving") : t("modules:admin.saveCompany")}</button></div>
    </form>}

    <section className="companyStructureSection" aria-labelledby="company-structure-title">
      <div className="companySectionHeading"><div><h2 id="company-structure-title">{t("modules:admin.companyStructure")}</h2><p className="muted">{t("modules:admin.companyStructureDescription")}</p></div></div>
      <div className="maintenanceTabs" role="tablist">{kinds.map((item) => <button key={item} role="tab" aria-selected={item === kind} className={item === kind ? "maintenanceTab active" : "maintenanceTab"} onClick={() => { setKind(item); choose(); }}>{t(`modules:admin.${item.replace("-", "")}`)}</button>)}</div>
      <div className="grid cols-2 companyStructureGrid">
        <div className="card"><div className="recordTitle companyListHeading"><h3>{t(`modules:admin.${kind.replace("-", "")}`)}</h3><button className="button smallButton" onClick={() => choose()}>{t("common:actions.add")}</button></div>{rows.length ? rows.map((row) => <button className="recordRow adminRoleRow" key={row.id} onClick={() => choose(row)}><span><strong>{row.name}</strong><span className="muted">{row.code}</span></span><span className={row.is_active ? "successBadge" : "dangerBadge"}>{row.is_active ? t("modules:admin.active") : t("modules:admin.inactive")}</span></button>) : <div className="companyEmptyState">{t("modules:admin.noSettings", { type: t(`modules:admin.${kind.replace("-", "")}`).toLowerCase() })}</div>}</div>
        <form className="card formGrid companySettingForm" onSubmit={save}><h3>{editing ? t("modules:admin.editSetting") : t("modules:admin.createSetting")}</h3><label>{t("modules:admin.code")}<input className="input" required value={code} onChange={(event) => setCode(event.target.value)} /></label><label>{t("modules:admin.name")}<input className="input" required value={name} onChange={(event) => setName(event.target.value)} /></label>{editing && <label className="checkboxLabel"><input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} />{t("modules:admin.active")}</label>}<div className="companySettingActions">{editing && <button className="secondaryButton" type="button" onClick={() => choose()}>{t("common:actions.cancel")}</button>}<button className="button" type="submit">{editing ? t("common:actions.save") : t("common:actions.add")}</button></div></form>
      </div>
    </section>
  </div>;
}
