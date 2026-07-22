"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiGet, buildQuery } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { AuditLog, PageResult } from "@/lib/types";
import { Pagination } from "@/components/maintenance/Maintenance";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import { translateNotification } from "@/i18n/translate";

export default function AuditLogsPage() {
  const { t } = useTranslation(["modules", "common"]);
  const { formatDateTime } = useLanguage();
  const { user } = useAuth();
  const [result, setResult] = useState<PageResult<AuditLog>>({ items: [], page: 1, page_size: 50, total: 0, pages: 0 });
  const [filters, setFilters] = useState({ search: "", action: "", entity_type: "", entity_id: "", from_date: "", to_date: "" });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (page = 1) => {
    if (user?.role !== "admin") return;
    setLoading(true); setError(null);
    try {
      setResult(await apiGet<PageResult<AuditLog>>(`/audit-logs${buildQuery({ ...filters, entity_id: filters.entity_id ? Number(filters.entity_id) : undefined, page, page_size: 50 })}`));
    } catch (err) { setError(err instanceof Error ? err.message : t("modules:auditLogs.loadError")); }
    finally { setLoading(false); }
  }, [filters, user]);

  useEffect(() => { void load(); }, [user]); // eslint-disable-line react-hooks/exhaustive-deps

  if (user?.role !== "admin") return <div className="error">{t("modules:auditLogs.accessDenied")}</div>;
  return <section>
    <div className="header"><div><h1>{t("modules:auditLogs.title")}</h1><p className="muted">{t("modules:auditLogs.description")}</p></div></div>
    {error && <div className="error spaced">{error}</div>}
    <div className="card filtersGrid spaced">
      <input className="input" placeholder={t("modules:auditLogs.searchPlaceholder")} value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} />
      <input className="input" placeholder={t("modules:auditLogs.actionPlaceholder")} value={filters.action} onChange={(e) => setFilters({ ...filters, action: e.target.value })} />
      <input className="input" placeholder={t("modules:auditLogs.entityTypePlaceholder")} value={filters.entity_type} onChange={(e) => setFilters({ ...filters, entity_type: e.target.value })} />
      <input className="input" type="number" placeholder={t("modules:auditLogs.entityIdPlaceholder")} value={filters.entity_id} onChange={(e) => setFilters({ ...filters, entity_id: e.target.value })} />
      <input className="input" type="date" value={filters.from_date} onChange={(e) => setFilters({ ...filters, from_date: e.target.value })} />
      <input className="input" type="date" value={filters.to_date} onChange={(e) => setFilters({ ...filters, to_date: e.target.value })} />
      <button className="button" type="button" onClick={() => void load(1)}>{t("common:actions.applyFilters")}</button>
    </div>
    {loading ? <div className="card">{t("modules:auditLogs.loading")}</div> : <div className="tableScroll"><table className="table">
      <thead><tr><th>{t("modules:auditLogs.dateTime")}</th><th>{t("common:labels.user")}</th><th>{t("modules:auditLogs.action")}</th><th>{t("modules:auditLogs.entity")}</th><th>{t("common:labels.description")}</th><th>{t("common:labels.details")}</th></tr></thead>
      <tbody>{result.items.map((log) => {
        const action = translateNotification(log.action_code ? `modules:auditActions.${log.action_code}` : null, log.description_params, log.action);
        const descriptionKey = log.description_key?.startsWith("audit.") ? `modules:auditDescriptions.${log.action_code}` : log.description_key;
        return <tr key={log.id}><td>{formatDateTime(log.created_at)}</td><td>{log.username ?? t("modules:auditLogs.system")}</td><td>{action}</td><td>{log.entity_type}{log.entity_id ? ` #${log.entity_id}` : ""}</td><td>{translateNotification(descriptionKey, log.description_params, action)}</td><td><details><summary className="linkButton">{t("common:actions.inspect")}</summary><pre className="auditJson">{JSON.stringify({ [t("modules:auditLogs.oldValues")]: log.old_values, [t("modules:auditLogs.newValues")]: log.new_values }, null, 2)}</pre></details></td></tr>;
      })}</tbody>
    </table></div>}
    <Pagination page={result.page} pages={result.pages} total={result.total} onPageChange={(page) => void load(page)} />
  </section>;
}
