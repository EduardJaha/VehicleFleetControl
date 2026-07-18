"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, buildQuery } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { AuditLog, PageResult } from "@/lib/types";
import { Pagination } from "@/components/maintenance/Maintenance";

export default function AuditLogsPage() {
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
    } catch (err) { setError(err instanceof Error ? err.message : "Could not load audit logs."); }
    finally { setLoading(false); }
  }, [filters, user]);

  useEffect(() => { void load(); }, [user]); // eslint-disable-line react-hooks/exhaustive-deps

  if (user?.role !== "admin") return <div className="error">Audit Logs are available to Admin users only.</div>;
  return <section>
    <div className="header"><div><h1>Audit Logs</h1><p className="muted">Permanent records of important user and system actions.</p></div></div>
    {error && <div className="error spaced">{error}</div>}
    <div className="card filtersGrid spaced">
      <input className="input" placeholder="Search user, action, description" value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} />
      <input className="input" placeholder="Action" value={filters.action} onChange={(e) => setFilters({ ...filters, action: e.target.value })} />
      <input className="input" placeholder="Entity type" value={filters.entity_type} onChange={(e) => setFilters({ ...filters, entity_type: e.target.value })} />
      <input className="input" type="number" placeholder="Entity ID" value={filters.entity_id} onChange={(e) => setFilters({ ...filters, entity_id: e.target.value })} />
      <input className="input" type="date" value={filters.from_date} onChange={(e) => setFilters({ ...filters, from_date: e.target.value })} />
      <input className="input" type="date" value={filters.to_date} onChange={(e) => setFilters({ ...filters, to_date: e.target.value })} />
      <button className="button" type="button" onClick={() => void load(1)}>Apply filters</button>
    </div>
    {loading ? <div className="card">Loading audit logs...</div> : <div className="tableScroll"><table className="table">
      <thead><tr><th>Date and time</th><th>User</th><th>Action</th><th>Entity</th><th>Description</th><th>Details</th></tr></thead>
      <tbody>{result.items.map((log) => <tr key={log.id}><td>{new Date(log.created_at).toLocaleString()}</td><td>{log.username ?? "System"}</td><td>{log.action}</td><td>{log.entity_type}{log.entity_id ? ` #${log.entity_id}` : ""}</td><td>{log.description ?? "-"}</td><td><details><summary className="linkButton">Inspect</summary><pre className="auditJson">{JSON.stringify({ old_values: log.old_values, new_values: log.new_values }, null, 2)}</pre></details></td></tr>)}</tbody>
    </table></div>}
    <Pagination page={result.page} pages={result.pages} total={result.total} onPageChange={(page) => void load(page)} />
  </section>;
}
