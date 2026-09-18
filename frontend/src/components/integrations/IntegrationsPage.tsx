"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { apiGet, apiPost } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLanguage } from "@/components/i18n/LanguageProvider";

type Key = { id: number; name: string; key_prefix: string; scopes: string[]; expires_at: string | null; last_used_at: string | null; revoked_at: string | null; created_at: string };
type Endpoint = { id: number; name: string; url: string; events: string[]; secret_version: number; revoked_at: string | null; created_at: string };
type Delivery = { id: number; delivery_id: string; event_id: string; event_type: string; status: string; payload: string; attempt_count: number; attempts: { number: number; started_at: string; outcome: string; http_status?: number; secret_version: number }[]; next_attempt_at: string; resend_of: number | null };
const base = "/admin/integrations";

export default function IntegrationsPage({ kind }: { kind: "api-keys" | "webhooks" }) {
  const { t } = useTranslation(["modules", "common"]);
  const { can } = useAuth();
  const { formatDateTime } = useLanguage();
  const isKeys = kind === "api-keys";
  const [keys, setKeys] = useState<Key[]>([]);
  const [endpoints, setEndpoints] = useState<Endpoint[]>([]);
  const [options, setOptions] = useState<string[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [expires, setExpires] = useState("");
  const [secret, setSecret] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [historyId, setHistoryId] = useState<number | null>(null);
  const [history, setHistory] = useState<Delivery[]>([]);
  const [more, setMore] = useState(false);
  const historyRequest = useRef(0);
  const showError = useCallback((reason: unknown) => setError(reason instanceof Error ? reason.message : t("modules:admin.requestFailed")), [t]);
  const load = useCallback(async () => {
    const [choices, rows] = await Promise.all([
      apiGet<{ scopes: string[]; events: string[] }>(`${base}/options`),
      apiGet<Key[] | Endpoint[]>(`${base}/${kind}`)
    ]);
    setOptions(isKeys ? choices.scopes : choices.events);
    if (isKeys) setKeys(rows as Key[]); else setEndpoints(rows as Endpoint[]);
  }, [kind, isKeys]);
  useEffect(() => {
    if (!can("integrations.manage")) return;
    let current = true;
    const historyRef = historyRequest;
    setLoading(true);
    void load().catch((reason) => { if (current) showError(reason); }).finally(() => { if (current) setLoading(false); });
    return () => { current = false; historyRef.current++; };
  }, [can, load, showError]);

  async function inspect(id: number, older = false) {
    const request = ++historyRequest.current;
    setError("");
    setHistoryId(id);
    if (!older) { setHistory([]); setMore(false); }
    try {
      const cursor = older && history.length ? `?before_id=${history[history.length - 1].id}` : "";
      const rows = await apiGet<Delivery[]>(`${base}/webhooks/${id}/deliveries${cursor}`);
      if (request !== historyRequest.current) return;
      setHistory((previous) => older ? [...previous, ...rows] : rows); setMore(rows.length === 50);
    } catch (reason) { if (request === historyRequest.current) showError(reason); }
  }
  async function mutate(path: string, payload: unknown = {}) {
    setBusy(true); setError(""); setSuccess(""); setSecret("");
    try {
      const result = await apiPost<{ raw_key?: string; secret?: string }>(`${base}/${path}`, payload);
      setSecret(result.raw_key || result.secret || "");
      setSuccess(t("modules:integrations.saved"));
      await load();
      if (historyId !== null) await inspect(historyId);
      return true;
    } catch (reason) { showError(reason); return false; }
    finally { setBusy(false); }
  }
  async function create(event: FormEvent) {
    event.preventDefault();
    const payload = isKeys ? { name, scopes: selected, expires_at: expires ? new Date(expires).toISOString() : null } : { name, url, events: selected };
    if (await mutate(kind, payload)) { setName(""); setUrl(""); setExpires(""); setSelected([]); }
  }
  const date = (value: string | null) => value ? formatDateTime(value.endsWith("Z") ? value : `${value}Z`) : "—";
  const label = (key: string) => t(`modules:integrations.${key}`);
  if (!can("integrations.manage")) return <div className="card">{t("modules:admin.noAccess")}</div>;
  return <div>
    <div className="header"><div><h1>{label(isKeys ? "apiKeys" : "webhooks")}</h1><p className="muted">{label(isKeys ? "keysDescription" : "hooksDescription")}</p></div></div>
    <nav className="actions"><Link href="/admin/integrations/api-keys">{label("apiKeys")}</Link><Link href="/admin/integrations/webhooks">{label("webhooks")}</Link></nav>
    {error && <div className="error spaced" role="alert">{error}</div>}
    {success && <p role="status">{success}</p>}
    {secret && <div className="card spaced"><h2>{label("saveSecret")}</h2><p>{label("shownOnce")}</p><code className="integrationSecret">{secret}</code><button className="button secondary" onClick={() => setSecret("")}>{label("dismiss")}</button></div>}
    <form className="card spaced" onSubmit={create}>
      <h2>{label("create")}</h2>
      <div className="formGrid">
        <label>{label("name")}<input className="input" required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} /></label>
        {isKeys ? <label>{label("expires")}<input className="input" type="datetime-local" value={expires} onChange={(e) => setExpires(e.target.value)} /></label> : <label>{label("url")}<input className="input" required type="url" maxLength={2048} placeholder="https://" value={url} onChange={(e) => setUrl(e.target.value)} /></label>}
      </div>
      <fieldset className="permissionGroup"><legend>{label(isKeys ? "scopes" : "events")}</legend>{options.map((option) => <label className="checkboxLabel" key={option}><input type="checkbox" checked={selected.includes(option)} onChange={(e) => setSelected((old) => e.target.checked ? [...old, option] : old.filter((value) => value !== option))} />{option}</label>)}</fieldset>
      <button className="button" disabled={busy || loading || !selected.length}>{label("create")}</button>
    </form>
    {loading ? <p role="status">{label("loading")}</p> : <div className="card spaced">
      <button className="button secondary" disabled={busy} onClick={() => { setError(""); void load().catch(showError); }}>{label("refresh")}</button>
      {!(isKeys ? keys : endpoints).length && <p>{label("empty")}</p>}
      <div className="tableWrap"><table><thead><tr><th>{label("name")}</th><th>{label(isKeys ? "scopes" : "events")}</th><th>{label("details")}</th><th>{label("actions")}</th></tr></thead><tbody>
        {(isKeys ? keys : endpoints).map((row) => <tr key={row.id}><td><strong>{row.name}</strong><p>{row.revoked_at ? label("revoked") : isKeys && (row as Key).expires_at && new Date(`${(row as Key).expires_at}Z`) <= new Date() ? label("expired") : label("active")}</p></td><td>{(isKeys ? (row as Key).scopes : (row as Endpoint).events).join(", ")}</td>
          <td>{isKeys ? <><code>{(row as Key).key_prefix}…</code><p>{label("lastUsed")}: {date((row as Key).last_used_at)}</p><p>{label("expires")}: {date((row as Key).expires_at)}</p></> : <><span>{(row as Endpoint).url}</span><p>{label("version")}: {(row as Endpoint).secret_version}</p></>}</td>
          <td><div className="actions"><button className="button secondary" disabled={busy || Boolean(row.revoked_at)} onClick={() => void mutate(`${kind}/${row.id}/rotate`)}>{label("rotate")}</button><button className="button danger" disabled={busy || Boolean(row.revoked_at)} onClick={() => void mutate(`${kind}/${row.id}/revoke`)}>{label("revoke")}</button>{!isKeys && <button className="button secondary" disabled={busy} onClick={() => void inspect(row.id)}>{label("deliveries")}</button>}</div></td></tr>)}
      </tbody></table></div>
    </div>}
    {!isKeys && historyId !== null && <section className="card spaced"><h2>{label("deliveries")} · {endpoints.find((row) => row.id === historyId)?.name}</h2><button className="button secondary" disabled={busy} onClick={() => void inspect(historyId)}>{label("refresh")}</button>{history.length === 0 && <p>{label("noDeliveries")}</p>}
      {history.map((delivery) => <details className="spaced" key={delivery.id}><summary>{delivery.event_type} · {label(`status.${delivery.status}`)} · {delivery.delivery_id}</summary><p>{label("eventId")}: {delivery.event_id}</p><p>{label("attempts")}: {delivery.attempt_count} · {label("nextAttempt")}: {date(delivery.next_attempt_at)}</p>{delivery.resend_of && <p>{label("resendOf")}: {delivery.resend_of}</p>}<pre className="integrationPayload">{JSON.stringify(JSON.parse(delivery.payload), null, 2)}</pre>
        <ul>{delivery.attempts.map((attempt) => <li key={attempt.number}>{date(attempt.started_at)} · {label(`outcome.${attempt.outcome}`)} · {attempt.http_status ?? "—"} · {label("version")} {attempt.secret_version}</li>)}</ul>
        <button className="button secondary" disabled={busy || !["Failed", "Dead", "Delivered"].includes(delivery.status) || Boolean(endpoints.find((row) => row.id === historyId)?.revoked_at)} onClick={() => void mutate(`deliveries/${delivery.id}/retry`)}>{label("retry")}</button>
      </details>)}{more && <button className="button secondary" disabled={busy} onClick={() => void inspect(historyId, true)}>{label("older")}</button>}
    </section>}
  </div>;
}
