"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { CreateEntityDialog } from "@/components/ui/CreateEntityDialog";
import { EntityPageHeader } from "@/components/ui/EntityPageHeader";
import { apiDownloadFile, apiGet, apiPost, apiPostForm, apiPut } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { toApiDate, todayInputDate } from "@/lib/format";
import type {
  ComplianceItem,
  ComplianceRate,
  DocumentComplianceDashboard,
  DocumentRequirement,
  DocumentVersion
} from "@/lib/types";

const emptyDocumentForm = {
  issue_date: todayInputDate(),
  expiry_date: "",
  document_number: "",
  issuing_authority: ""
};

const emptyRequirementForm = {
  document_type: "",
  applies_to_vehicle_category: "",
  applies_to_country: "",
  applies_to_driver: false,
  required: true,
  validity_months: "",
  warning_days: "30",
  is_active: true
};

function statusClass(status: string) {
  if (status === "Expired" || status === "Missing" || status === "Rejected") return "error";
  if (status === "Expiring Soon" || status === "Renewal In Progress") return "badge";
  return "success";
}

export default function DocumentCompliancePage() {
  const { t } = useTranslation(["modules", "common"]);
  const { user, can } = useAuth();
  const canWrite = can("papersWrite") || user?.role === "driver";
  const [dashboard, setDashboard] = useState<DocumentComplianceDashboard | null>(null);
  const [requirements, setRequirements] = useState<DocumentRequirement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<ComplianceItem | null>(null);
  const [documentForm, setDocumentForm] = useState(emptyDocumentForm);
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [requirementOpen, setRequirementOpen] = useState(false);
  const [requirementForm, setRequirementForm] = useState(emptyRequirementForm);
  const [versions, setVersions] = useState<DocumentVersion[] | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [summary, rules] = await Promise.all([
        apiGet<DocumentComplianceDashboard>("/compliance/documents"),
        apiGet<DocumentRequirement[]>("/compliance/document-requirements")
      ]);
      setDashboard(summary);
      setRequirements(rules);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:documentCompliance.loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { void load(); }, [load]);

  const items = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (dashboard?.items ?? []).filter((item) => (
      (!statusFilter || item.status === statusFilter)
      && (!term || [item.owner_name, item.document_type, item.department, item.location]
        .some((value) => (value ?? "").toLowerCase().includes(term)))
    ));
  }, [dashboard, search, statusFilter]);

  async function saveDocument(event: React.FormEvent) {
    event.preventDefault();
    if (!selected || !file) return;
    setSubmitting(true);
    setError(null);
    try {
      const data = new FormData();
      data.append("issue_date", toApiDate(documentForm.issue_date));
      data.append("expiry_date", toApiDate(documentForm.expiry_date));
      data.append("document_number", documentForm.document_number);
      data.append("issuing_authority", documentForm.issuing_authority);
      data.append("file", file);
      let path = `/compliance/documents/${selected.document_id}/renew`;
      if (!selected.document_id) {
        path = "/compliance/documents";
        data.append("owner_type", selected.owner_type);
        data.append("owner_id", String(selected.owner_id));
        data.append("requirement_id", String(selected.requirement_id));
      }
      await apiPostForm<DocumentVersion>(path, data);
      setMessage(t(selected.document_id ? "modules:documentCompliance.renewalStarted" : "modules:documentCompliance.uploaded"));
      setSelected(null);
      setFile(null);
      setDocumentForm(emptyDocumentForm);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:documentCompliance.saveError"));
    } finally {
      setSubmitting(false);
    }
  }

  async function createRequirement(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await apiPost<DocumentRequirement>("/compliance/document-requirements", {
        ...requirementForm,
        applies_to_vehicle_category: requirementForm.applies_to_vehicle_category || null,
        applies_to_country: requirementForm.applies_to_country || null,
        validity_months: requirementForm.validity_months ? Number(requirementForm.validity_months) : null,
        warning_days: Number(requirementForm.warning_days)
      });
      setRequirementOpen(false);
      setRequirementForm(emptyRequirementForm);
      setMessage(t("modules:documentCompliance.requirementCreated"));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:documentCompliance.saveError"));
    } finally {
      setSubmitting(false);
    }
  }

  async function showVersions(item: ComplianceItem) {
    if (!item.document_id) return;
    setError(null);
    try {
      setVersions(await apiGet<DocumentVersion[]>(`/compliance/documents/${item.document_id}/versions`));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:documentCompliance.loadError"));
    }
  }

  async function deactivateRequirement(requirement: DocumentRequirement) {
    setError(null);
    try {
      await apiPut<DocumentRequirement>(`/compliance/document-requirements/${requirement.id}`, {
        document_type: requirement.document_type,
        applies_to_vehicle_category: requirement.applies_to_vehicle_category,
        applies_to_country: requirement.applies_to_country,
        applies_to_driver: requirement.applies_to_driver,
        required: requirement.required,
        validity_months: requirement.validity_months,
        warning_days: requirement.warning_days,
        is_active: false
      });
      setMessage(t("modules:documentCompliance.requirementDeactivated"));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:documentCompliance.saveError"));
    }
  }

  async function verify(version: DocumentVersion, approved: boolean) {
    const rejectionReason = approved ? null : window.prompt(t("modules:documentCompliance.rejectionPrompt"));
    if (!approved && !rejectionReason) return;
    await apiPost<DocumentVersion>(`/compliance/document-versions/${version.id}/verify`, {
      approved,
      rejection_reason: rejectionReason
    });
    setVersions(null);
    setMessage(t(approved ? "modules:documentCompliance.approved" : "modules:documentCompliance.rejected"));
    await load();
  }

  const rateSections: Array<[string, ComplianceRate[]]> = [
    [t("modules:documentCompliance.byVehicle"), dashboard?.compliance_by_vehicle ?? []],
    [t("modules:documentCompliance.byDriver"), dashboard?.compliance_by_driver ?? []],
    [t("modules:documentCompliance.byDepartment"), dashboard?.compliance_by_department ?? []],
    [t("modules:documentCompliance.byLocation"), dashboard?.compliance_by_location ?? []]
  ];

  return (
    <section>
      <EntityPageHeader
        title={t("modules:documentCompliance.title")}
        description={t("modules:documentCompliance.description")}
        actionLabel={user?.role === "admin" ? t("modules:documentCompliance.addRequirement") : undefined}
        onAction={user?.role === "admin" ? () => setRequirementOpen(true) : undefined}
      />
      {error && <div className="error spaced" role="alert">{error}</div>}
      {message && <div className="success spaced" role="status">{message}</div>}

      <div className="kpiGrid spaced">
        {[
          [t("modules:documentCompliance.complianceRate"), `${dashboard?.overall_compliance_rate ?? 0}%`],
          [t("modules:documentCompliance.missing"), dashboard?.missing_required.length ?? 0],
          [t("modules:documentCompliance.expired"), dashboard?.expired.length ?? 0],
          [t("modules:documentCompliance.expiring7"), dashboard?.expiring_in_7_days.length ?? 0],
          [t("modules:documentCompliance.expiring30"), dashboard?.expiring_in_30_days.length ?? 0],
          [t("modules:documentCompliance.renewals"), dashboard?.renewal_in_progress.length ?? 0]
        ].map(([label, value]) => <div className="card" key={String(label)}><div className="kpiLabel">{label}</div><div className="kpiValue">{value}</div></div>)}
      </div>

      <div className="card filtersGrid spaced">
        <input className="input" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("modules:documentCompliance.search")} />
        <select className="select" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
          <option value="">{t("modules:documentCompliance.allStatuses")}</option>
          {["Missing", "Valid", "Expiring Soon", "Expired", "Renewal In Progress", "Rejected", "Archived"].map((status) => <option key={status} value={status}>{t(`common:status.${status}`)}</option>)}
        </select>
      </div>

      {loading ? <div className="card">{t("common:states.loading")}</div> : <div className="tableScroll">
        <table className="table">
          <thead><tr><th>{t("modules:documentCompliance.owner")}</th><th>{t("modules:documents.document")}</th><th>{t("common:labels.department")}</th><th>{t("common:labels.location")}</th><th>{t("common:labels.expiryDate")}</th><th>{t("common:labels.status")}</th><th>{t("common:labels.actions")}</th></tr></thead>
          <tbody>
            {items.map((item) => <tr key={`${item.requirement_id}-${item.owner_type}-${item.owner_id}`}>
              <td><strong>{item.owner_name}</strong><div className="muted">{item.owner_type}</div></td>
              <td>{item.document_type}</td><td>{item.department ?? "-"}</td><td>{item.location ?? "-"}</td><td>{item.expiry_date ?? "-"}</td>
              <td><span className={statusClass(item.status)}>{t(`common:status.${item.status}`)}</span></td>
              <td><div className="actions">
                {item.file_path && <button className="linkButton" type="button" onClick={() => void apiDownloadFile(item.file_path!, `${item.document_type}.pdf`)}>{t("common:actions.download")}</button>}
                {item.document_id && <button className="secondaryButton smallButton" type="button" onClick={() => void showVersions(item)}>{t("modules:documentCompliance.history")}</button>}
                {canWrite && <button className="button smallButton" type="button" onClick={() => { setSelected(item); setDocumentForm({ ...emptyDocumentForm }); setFile(null); }}>{item.document_id ? t("modules:documentCompliance.renew") : t("modules:documentCompliance.upload")}</button>}
              </div></td>
            </tr>)}
            {items.length === 0 && <tr><td colSpan={7} className="muted">{t("modules:documentCompliance.empty")}</td></tr>}
          </tbody>
        </table>
      </div>}

      <div className="maintenanceSections spaced">
        {rateSections.map(([title, rates]) => <div className="card" key={title}><h2>{title}</h2><div className="recordList">
          {rates.map((rate) => <div className="recordRow" key={rate.name}><span>{rate.name}<span className="muted"> · {rate.compliant}/{rate.required}</span></span><strong>{rate.rate}%</strong></div>)}
          {rates.length === 0 && <p className="muted">{t("modules:documentCompliance.empty")}</p>}
        </div></div>)}
      </div>

      {user?.role === "admin" && <div className="card spaced">
        <h2>{t("modules:documentCompliance.requirements")}</h2>
        <div className="tableScroll"><table className="table">
          <thead><tr><th>{t("modules:documents.documentType")}</th><th>{t("modules:documentCompliance.scope")}</th><th>{t("modules:documentCompliance.validityMonths")}</th><th>{t("modules:documentCompliance.warningDays")}</th><th>{t("common:labels.actions")}</th></tr></thead>
          <tbody>{requirements.map((requirement) => <tr key={requirement.id}>
            <td>{requirement.document_type}</td>
            <td>{requirement.applies_to_driver ? t("common:labels.driver") : requirement.applies_to_country || requirement.applies_to_vehicle_category || t("modules:documentCompliance.allVehicles")}</td>
            <td>{requirement.validity_months ?? "-"}</td><td>{requirement.warning_days}</td>
            <td><button className="dangerButton smallButton" type="button" onClick={() => void deactivateRequirement(requirement)}>{t("modules:documentCompliance.deactivate")}</button></td>
          </tr>)}</tbody>
        </table></div>
      </div>}

      <CreateEntityDialog open={!!selected} title={selected?.document_id ? t("modules:documentCompliance.renew") : t("modules:documentCompliance.upload")} busy={submitting} onClose={() => setSelected(null)}>
        <form className="form dialogForm" onSubmit={saveDocument}>
          <p>{selected?.owner_name} · {selected?.document_type}</p>
          <div className="formGrid">
            <div className="formRow"><label>{t("common:labels.issueDate")}</label><input className="input" type="date" value={documentForm.issue_date} onChange={(event) => setDocumentForm({ ...documentForm, issue_date: event.target.value })} required /></div>
            <div className="formRow"><label>{t("common:labels.expiryDate")}</label><input className="input" type="date" min={documentForm.issue_date} value={documentForm.expiry_date} onChange={(event) => setDocumentForm({ ...documentForm, expiry_date: event.target.value })} required /></div>
            <div className="formRow"><label>{t("modules:documentCompliance.documentNumber")}</label><input className="input" value={documentForm.document_number} onChange={(event) => setDocumentForm({ ...documentForm, document_number: event.target.value })} /></div>
            <div className="formRow"><label>{t("modules:documentCompliance.issuingAuthority")}</label><input className="input" value={documentForm.issuing_authority} onChange={(event) => setDocumentForm({ ...documentForm, issuing_authority: event.target.value })} /></div>
            <div className="formRow span2"><label>{t("common:labels.file")}</label><input className="input" type="file" accept=".pdf,application/pdf" onChange={(event) => setFile(event.target.files?.[0] ?? null)} required /></div>
          </div>
          <div className="actions dialogActions"><button className="secondaryButton" type="button" onClick={() => setSelected(null)}>{t("common:actions.cancel")}</button><button className="button" disabled={submitting || !file}>{t("common:actions.save")}</button></div>
        </form>
      </CreateEntityDialog>

      <CreateEntityDialog open={requirementOpen} title={t("modules:documentCompliance.addRequirement")} busy={submitting} onClose={() => setRequirementOpen(false)}>
        <form className="form dialogForm" onSubmit={createRequirement}>
          <div className="formGrid">
            <div className="formRow span2"><label>{t("modules:documents.documentType")}</label><input className="input" value={requirementForm.document_type} onChange={(event) => setRequirementForm({ ...requirementForm, document_type: event.target.value })} required /></div>
            <div className="formRow"><label>{t("modules:documentCompliance.country")}</label><select className="select" value={requirementForm.applies_to_country} disabled={requirementForm.applies_to_driver} onChange={(event) => setRequirementForm({ ...requirementForm, applies_to_country: event.target.value })}><option value="">-</option><option value="XK">Kosovo</option><option value="AL">Albania</option></select></div>
            <div className="formRow"><label>{t("modules:documentCompliance.category")}</label><input className="input" value={requirementForm.applies_to_vehicle_category} disabled={requirementForm.applies_to_driver} onChange={(event) => setRequirementForm({ ...requirementForm, applies_to_vehicle_category: event.target.value })} /></div>
            <div className="formRow"><label>{t("modules:documentCompliance.validityMonths")}</label><input className="input" type="number" min="1" value={requirementForm.validity_months} onChange={(event) => setRequirementForm({ ...requirementForm, validity_months: event.target.value })} /></div>
            <div className="formRow"><label>{t("modules:documentCompliance.warningDays")}</label><input className="input" type="number" min="0" value={requirementForm.warning_days} onChange={(event) => setRequirementForm({ ...requirementForm, warning_days: event.target.value })} required /></div>
            <label><input type="checkbox" checked={requirementForm.applies_to_driver} onChange={(event) => setRequirementForm({ ...requirementForm, applies_to_driver: event.target.checked, applies_to_country: "", applies_to_vehicle_category: "" })} /> {t("modules:documentCompliance.appliesToDriver")}</label>
            <label><input type="checkbox" checked={requirementForm.required} onChange={(event) => setRequirementForm({ ...requirementForm, required: event.target.checked })} /> {t("modules:documentCompliance.required")}</label>
          </div>
          <div className="actions dialogActions"><button className="secondaryButton" type="button" onClick={() => setRequirementOpen(false)}>{t("common:actions.cancel")}</button><button className="button" disabled={submitting}>{t("common:actions.save")}</button></div>
        </form>
      </CreateEntityDialog>

      <CreateEntityDialog open={versions !== null} title={t("modules:documentCompliance.history")} onClose={() => setVersions(null)}>
        <div className="recordList">
          {(versions ?? []).map((version) => <div className="linkedRecordCard" key={version.id}>
            <div><strong>v{version.version_number}</strong> {version.is_current && <span className="badge">{t("modules:documentCompliance.current")}</span>}</div>
            <div>{version.issue_date} → {version.expiry_date}</div>
            <div className="muted">{t(`common:status.${version.renewal_status}`)}{version.rejection_reason ? ` · ${version.rejection_reason}` : ""}</div>
            <div className="actions"><button className="linkButton" onClick={() => void apiDownloadFile(version.file_path, `document-v${version.version_number}.pdf`)}>{t("common:actions.download")}</button>
              {can("papersWrite") && !version.verified_at && <><button className="button smallButton" onClick={() => void verify(version, true)}>{t("modules:documentCompliance.approve")}</button><button className="dangerButton smallButton" onClick={() => void verify(version, false)}>{t("modules:documentCompliance.reject")}</button></>}
            </div>
          </div>)}
        </div>
      </CreateEntityDialog>
    </section>
  );
}
