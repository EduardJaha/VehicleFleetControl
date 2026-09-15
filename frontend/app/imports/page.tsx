"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { EntityPageHeader } from "@/components/ui/EntityPageHeader";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import { apiDownload, apiGet, apiPost, apiPostForm } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type {
  ImportEntityType, ImportFieldDefinition, ImportJob, ImportTransactionMode,
  ImportUpdateMode, ImportUpload, PageResult
} from "@/lib/types";

const ENTITIES: ImportEntityType[] = [
  "Vehicles", "Drivers", "Historical Services", "Fuel and Charging Records",
  "Documents Metadata", "Vehicle Assignments", "Vendors", "Parts"
];
const ENABLED = new Set<ImportEntityType>(ENTITIES);

function entityFields(definitions: ImportFieldDefinition[], t: (key: string, options: { defaultValue: string }) => string) {
  return definitions.map((field) => ({ ...field, label: t(`modules:imports.fields.${field.key}`, { defaultValue: field.label }) }));
}

export default function ImportsPage() {
  const { t } = useTranslation(["modules", "common", "errors"]);
  const { language, formatDateTime, formatNumber } = useLanguage();
  const { can } = useAuth();
  const allowed = can("importsWrite");
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [entity, setEntity] = useState<ImportEntityType>("Vehicles");
  const [file, setFile] = useState<File | null>(null);
  const [current, setCurrent] = useState<ImportJob | null>(null);
  const [headers, setHeaders] = useState<string[]>([]);
  const [fields, setFields] = useState<ImportFieldDefinition[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [updateMode, setUpdateMode] = useState<ImportUpdateMode>("create_only");
  const [transactionMode, setTransactionMode] = useState<ImportTransactionMode>("row");
  const [busy, setBusy] = useState<"upload" | "validate" | "confirm" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const workflow = t("modules:imports.workflow", { returnObjects: true }) as unknown as string[];
  const summary = useMemo(() => current ? [
    ["total", current.total_rows], ["valid", current.valid_rows], ["invalid", current.invalid_rows],
    ["created", current.created_rows], ["updated", current.updated_rows], ["skipped", current.skipped_rows]
  ] as Array<[string, number]> : [], [current]);

  async function loadJobs() {
    try {
      const result = await apiGet<PageResult<ImportJob>>("/imports?page=1&page_size=50");
      setJobs(result.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:imports.loadError"));
    }
  }

  useEffect(() => {
    if (allowed) void loadJobs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allowed]);

  const currentId = current?.id;
  const currentStatus = current?.status;
  useEffect(() => {
    if (!currentId || !(busy === "validate" || busy === "confirm" || currentStatus === "Validating" || currentStatus === "Importing")) return;
    let cancelled = false;
    const timer = window.setInterval(async () => {
      try {
        const progress = await apiGet<ImportJob>(`/imports/${currentId}?row_limit=0`);
        if (!busy && progress.status !== "Validating" && progress.status !== "Importing") {
          const detail = await apiGet<ImportJob>(`/imports/${currentId}`);
          if (!cancelled) setCurrent((previous) => previous?.id === detail.id ? detail : previous);
          return;
        }
        if (!cancelled) setCurrent((previous) => previous?.id === progress.id ? { ...previous, phase: progress.phase, progress_percent: progress.progress_percent } : previous);
      } catch { /* The mutation request reports failures. */ }
    }, 750);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [currentId, currentStatus, busy]);

  const validationChanged = !!current && (updateMode !== current.update_mode ||
    JSON.stringify(Object.entries(mapping).filter(([, value]) => value).sort()) !==
    JSON.stringify(Object.entries(current.column_mapping ?? {}).filter(([, value]) => value).sort()));

  function chooseEntity(next: ImportEntityType) {
    setEntity(next);
    setFile(null);
    setCurrent(null);
    setHeaders([]);
    setFields([]);
    setUpdateMode("create_only");
    setMapping({});
    setError(null);
  }

  async function downloadTemplate(format: "csv" | "xlsx") {
    const stem = entity.toLowerCase().replaceAll(" ", "-");
    await apiDownload(`/imports/templates/${encodeURIComponent(entity)}?format=${format}&language=${language}`, `${stem}-import-template-${language}.${format}`);
  }

  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file || !ENABLED.has(entity)) return;
    setBusy("upload");
    setError(null);
    try {
      const form = new FormData();
      form.set("entity_type", entity);
      form.set("file", file);
      const result = await apiPostForm<ImportUpload>("/imports/upload", form);
      setHeaders(result.headers);
      setFields(entityFields(result.fields, t));
      setUpdateMode("create_only");
      setMapping(result.suggested_mapping);
      setCurrent(await apiGet<ImportJob>(`/imports/${result.id}`));
      await loadJobs();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:imports.uploadError"));
    } finally {
      setBusy(null);
    }
  }

  async function validate() {
    if (!current) return;
    setBusy("validate");
    setCurrent({ ...current, phase: "Validating", progress_percent: 0 });
    setError(null);
    try {
      const result = await apiPost<ImportJob>(`/imports/${current.id}/validate`, { column_mapping: mapping, update_mode: updateMode });
      setCurrent(result);
      await loadJobs();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:imports.validateError"));
    } finally {
      setBusy(null);
    }
  }

  async function confirmImport() {
    if (!current || !window.confirm(t("modules:imports.confirmPrompt"))) return;
    setBusy("confirm");
    setCurrent({ ...current, phase: "Importing", progress_percent: 0 });
    setError(null);
    try {
      const result = await apiPost<ImportJob>(`/imports/${current.id}/confirm`, { update_mode: updateMode, transaction_mode: transactionMode });
      setCurrent(result);
      await loadJobs();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:imports.confirmError"));
    } finally {
      setBusy(null);
    }
  }

  async function openJob(job: ImportJob) {
    setError(null);
    try {
      const detail = await apiGet<ImportJob>(`/imports/${job.id}`);
      setEntity(detail.entity_type);
      setCurrent(detail);
      setHeaders(detail.source_headers);
      setFields(entityFields(detail.fields ?? [], t));
      setMapping(detail.column_mapping ?? {});
      setUpdateMode(detail.update_mode ?? "create_only");
      setTransactionMode(detail.transaction_mode ?? "row");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:imports.loadError"));
    }
  }

  function errorText(code?: string, fallback?: string) {
    if (code && t(`errors:${code}`, { defaultValue: "" })) return t(`errors:${code}`);
    return fallback || t("errors:invalid_value");
  }

  if (!allowed) return <div className="error">{t("modules:imports.accessDenied")}</div>;

  return (
    <section>
      <EntityPageHeader title={t("modules:imports.title")} description={t("modules:imports.description")} />

      <ol className="importWorkflow" aria-label={t("modules:imports.title")}>
        {workflow.map((step, index) => <li key={step}><span>{index + 1}</span>{step}</li>)}
      </ol>

      {error && <div className="error spaced" role="alert">{error}</div>}

      <div className="grid cols-2 importLayout">
        <form className="card form fullWidthForm" onSubmit={upload}>
          <h2>{t("modules:imports.newImport")}</h2>
          <div className="formRow">
            <label htmlFor="import-entity">{t("modules:imports.entityType")}</label>
            <select id="import-entity" className="select" value={entity} disabled={busy !== null} onChange={(event) => chooseEntity(event.target.value as ImportEntityType)}>
              {ENTITIES.map((item) => <option key={item} value={item}>{t(`modules:imports.entities.${item}`)}{!ENABLED.has(item) ? ` — ${t("modules:imports.planned")}` : ""}</option>)}
            </select>
          </div>
          {ENABLED.has(entity) ? <>
            <div className="actions">
              <button className="secondaryButton" type="button" onClick={() => void downloadTemplate("csv")}>{t("modules:imports.downloadCsv")}</button>
              <button className="secondaryButton" type="button" onClick={() => void downloadTemplate("xlsx")}>{t("modules:imports.downloadExcel")}</button>
            </div>
            <div className="formRow">
              <label htmlFor="import-file">{t("modules:imports.chooseFile")}</label>
              <input id="import-file" className="input" type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(event) => setFile(event.target.files?.[0] ?? null)} required />
            </div>
            <button className="button" type="submit" disabled={!file || busy !== null}>{busy === "upload" ? t("modules:imports.uploading") : t("modules:imports.upload")}</button>
          </> : <div className="importPlanned">{t("modules:imports.planned")}</div>}
        </form>

        <div className="card">
          <h2>{t("modules:imports.history")}</h2>
          {jobs.length === 0 ? <p className="muted">{t("modules:imports.noJobs")}</p> : <div className="recordList">
            {jobs.map((job) => <button className="importHistoryRow" type="button" disabled={busy !== null} key={job.id} onClick={() => void openJob(job)}>
              <span><strong>#{job.id} · {job.filename}</strong><small>{t(`modules:imports.entities.${job.entity_type}`)} · {formatDateTime(job.created_at)}</small></span>
              <span className="badge">{t(`modules:imports.statuses.${job.status}`)}</span>
            </button>)}
          </div>}
        </div>
      </div>

      {current && (busy === "validate" || busy === "confirm" || current.status === "Validating" || current.status === "Importing") && <div className="card spaced" role="status">
        <label htmlFor="import-progress">{t(`modules:imports.statuses.${current.phase === "Importing" || busy === "confirm" ? "Importing" : "Validating"}`)} · {current.progress_percent ?? 0}%</label>
        <progress id="import-progress" value={current.progress_percent ?? 0} max={100} />
      </div>}

      {current && headers.length > 0 && (current.status === "Uploaded" || current.status === "Ready") && <div className="card spaced">
        <h2>{t("modules:imports.mapping")}</h2>
        <p className="muted">{t("modules:imports.dryRunHelp")}</p>
        <p className="muted">{t("modules:imports.historyHelp")}</p>
        <div className="importMapping">
          {fields.map((field) => <div className="formRow" key={field.key}>
            <label htmlFor={`mapping-${field.key}`}>{t(`modules:imports.fields.${field.key}`, { defaultValue: field.label })} {field.required && <span className="requiredMark">({t("modules:imports.required")})</span>}</label>
            <select id={`mapping-${field.key}`} className="select" value={mapping[field.key] ?? ""} disabled={busy !== null} onChange={(event) => setMapping((value) => ({ ...value, [field.key]: event.target.value }))}>
              <option value="">{t("modules:imports.notMapped")}</option>
              {headers.map((header) => <option key={header} value={header}>{header}</option>)}
            </select>
          </div>)}
        </div>
        <div className="formRow importMode">
          <label htmlFor="update-mode">{t("modules:imports.updateMode")}</label>
          <select id="update-mode" className="select" value={updateMode} disabled={busy !== null} onChange={(event) => setUpdateMode(event.target.value as ImportUpdateMode)}>
            <option value="create_only">{t("modules:imports.createOnly")}</option>
            <option value="create_or_skip">{t("modules:imports.createOrSkip")}</option>
            <option value="update_existing">{t("modules:imports.updateExisting")}</option>
          </select>
          {updateMode === "update_existing" && <div className="errorText">{t("modules:imports.updateWarning")}</div>}
        </div>
        <button className="button" type="button" disabled={busy !== null} onClick={() => void validate()}>{busy === "validate" ? t("modules:imports.validating") : t("modules:imports.validate")}</button>
      </div>}

      {current && current.status !== "Uploaded" && <div className="card spaced">
        <div className="recordTitle"><h2>{t("modules:imports.summary")} #{current.id}</h2><span className="badge">{t(`modules:imports.statuses.${current.status}`)}</span></div>
        <div className="importSummary">
          {summary.map(([label, value]) => <div key={label}><span>{t(`modules:imports.${label}`)}</span><strong>{formatNumber(value)}</strong></div>)}
        </div>
        <div className="actions">
          {current.error_report_path && <button className="secondaryButton" type="button" onClick={() => void apiDownload(`${current.error_report_path!}?language=${language}`, `import-${current.id}-errors.csv`)}>{t("modules:imports.errorReport")}</button>}
          {current.status === "Ready" && <>
            <label className="formRow importTransaction"><span>{t("modules:imports.transactionMode")}</span><select className="select" value={transactionMode} onChange={(event) => setTransactionMode(event.target.value as ImportTransactionMode)}><option value="row">{t("modules:imports.rowTransaction")}</option><option value="file">{t("modules:imports.fileTransaction")}</option></select></label>
            <button className="button" type="button" disabled={busy !== null || current.valid_rows === 0 || validationChanged || (transactionMode === "file" && current.invalid_rows > 0)} onClick={() => void confirmImport()}>{busy === "confirm" ? t("modules:imports.confirming") : t("modules:imports.confirm")}</button>
          </>}
        </div>
      </div>}

      {current && current.rows.length > 0 && <div className="spaced">
        <h2>{t("modules:imports.preview")}</h2>
        <div className="tableScroll"><table className="table importPreview"><thead><tr><th>{t("modules:imports.row")}</th><th>{t("modules:imports.result")}</th><th>{t("modules:imports.proposedAction")}</th><th>{t("modules:imports.values")}</th><th>{t("modules:imports.errors")}</th></tr></thead><tbody>
          {current.rows.map((row) => <tr key={row.id}><td>{row.row_number}</td><td><span className={row.status === "Invalid" || row.status === "Failed" ? "dangerBadge" : "successBadge"}>{t(`modules:imports.statuses.${row.status}`, { defaultValue: row.status })}</span></td><td>{t(`modules:imports.actions.${row.action}`, { defaultValue: row.action })}</td><td><details><summary>{t("modules:imports.values")}</summary><dl>{Object.entries(row.mapped_data ?? {}).map(([key, value]) => <div key={key}><dt>{t(`modules:imports.fields.${key}`, { defaultValue: key })}</dt><dd>{String(value ?? "—")}</dd></div>)}</dl></details></td><td>{row.errors.length ? <ul className="importErrors">{row.errors.map((item, index) => <li key={`${item.code}-${index}`}><strong>{item.field}</strong>: {errorText(item.code, item.message)}</li>)}</ul> : <span className="muted">{t("modules:imports.noErrors")}</span>}{(row.warnings ?? []).map((warning, index) => <p key={index} className="warningText">{t("modules:imports.warning")}: {errorText(warning.code, warning.message)}</p>)}</td></tr>)}
        </tbody></table></div>
      </div>}
    </section>
  );
}
