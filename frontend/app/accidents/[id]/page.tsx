"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiDownloadFile, apiGet, apiPost, apiPostForm, apiPut } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import type { AccidentDetail, ApiMessage } from "@/lib/types";

const TABS = ["summary", "people", "claim", "repair", "attachments", "timeline"] as const;
type Tab = typeof TABS[number];

const initialClaim = {
  insurance_company: "",
  policy_number: "",
  claim_number: "",
  claim_status: "Open",
  claim_opened_date: new Date().toISOString().slice(0, 10),
  insurance_document_id: "",
  settlement_amount: "",
  deductible: "",
  adjuster_name: "",
  notes: ""
};

function Details({ rows }: { rows: Array<[string, React.ReactNode]> }) {
  return <dl className="detailList">{rows.map(([label, value]) => <div key={label} style={{ display: "contents" }}><dt>{label}</dt><dd>{value ?? "-"}</dd></div>)}</dl>;
}

export default function AccidentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { t } = useTranslation(["modules", "common"]);
  const { formatCurrency, formatDate, formatDateTime } = useLanguage();
  const { can } = useAuth();
  const canManage = can("accidentsWrite");
  const canClaim = can("claimsWrite");
  const [accident, setAccident] = useState<AccidentDetail | null>(null);
  const [tab, setTab] = useState<Tab>("summary");
  const [claim, setClaim] = useState(initialClaim);
  const [upload, setUpload] = useState<File | null>(null);
  const [repairEstimate, setRepairEstimate] = useState("");
  const [party, setParty] = useState({ party_type: "Third Party", name: "", phone: "" });
  const [injury, setInjury] = useState({ injured_person_name: "", injury_severity: "Minor", party_id: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      const detail = await apiGet<AccidentDetail>(`/accidents/id/${id}/detail`);
      setAccident(detail);
      setRepairEstimate(detail.estimated_damage_cost == null ? "" : String(detail.estimated_damage_cost));
      if (detail.claim) {
        setClaim({
          insurance_company: detail.claim.insurance_company,
          policy_number: detail.claim.policy_number,
          claim_number: detail.claim.claim_number,
          claim_status: detail.claim.claim_status,
          claim_opened_date: detail.claim.claim_opened_date.slice(0, 10),
          insurance_document_id: detail.claim.insurance_document_id ? String(detail.claim.insurance_document_id) : "",
          settlement_amount: detail.claim.settlement_amount ?? "",
          deductible: detail.claim.deductible ?? "",
          adjuster_name: detail.claim.adjuster_name ?? "",
          notes: detail.claim.notes ?? ""
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:accidents.loadError"));
    }
  }

  useEffect(() => { void load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function action(path: string, body: unknown = {}) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await apiPost<ApiMessage>(`/accidents/id/${id}/${path}`, body);
      setMessage(result.message ?? t("modules:accidents.actionCompleted"));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:accidents.actionError"));
    } finally {
      setBusy(false);
    }
  }

  async function saveClaim(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const payload = {
      ...claim,
      insurance_document_id: claim.insurance_document_id ? Number(claim.insurance_document_id) : null,
      settlement_amount: claim.settlement_amount || null,
      deductible: claim.deductible || null,
      claim_opened_date: new Date(`${claim.claim_opened_date}T00:00:00`).toISOString()
      };
      const result = accident?.claim
        ? await apiPut<ApiMessage>(`/accidents/id/${id}/claim`, payload)
        : await apiPost<ApiMessage>(`/accidents/id/${id}/claim`, payload);
      setMessage(result.message ?? t("modules:accidents.actionCompleted"));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:accidents.actionError"));
    } finally {
      setBusy(false);
    }
  }

  async function uploadAttachment(event: React.FormEvent) {
    event.preventDefault();
    if (!upload) return;
    setBusy(true);
    try {
      const data = new FormData();
      data.append("entity_type", "VehicleAccident");
      data.append("entity_id", id);
      data.append("category", "auto");
      data.append("file", upload);
      await apiPostForm<ApiMessage>("/files", data);
      setUpload(null);
      setMessage(t("modules:accidents.attachmentUploaded"));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("modules:accidents.actionError"));
    } finally {
      setBusy(false);
    }
  }

  async function addParty(event: React.FormEvent) {
    event.preventDefault();
    await action("parties", { ...party, phone: party.phone || null });
    setParty({ party_type: "Third Party", name: "", phone: "" });
  }

  async function addInjury(event: React.FormEvent) {
    event.preventDefault();
    await action("injuries", {
      injured_person_name: injury.injured_person_name,
      injury_severity: injury.injury_severity,
      party_id: injury.party_id ? Number(injury.party_id) : null
    });
    setInjury({ injured_person_name: "", injury_severity: "Minor", party_id: "" });
  }

  if (!accident) return <section>{error ? <div className="error">{error}</div> : <div className="card">{t("modules:accidents.loading")}</div>}</section>;

  return (
    <section>
      <div className="header">
        <div>
          <Link className="link" href="/accidents">← {t("modules:accidents.back")}</Link>
          <h1>{t("modules:accidents.detailTitle", { id: accident.id })}</h1>
          <p className="muted">{accident.license_plate} · {accident.location}</p>
        </div>
        <span className={accident.status === "Closed" || accident.status === "Resolved" ? "successBadge" : "warningBadge"}>{accident.status}</span>
      </div>

      {error && <div className="error spaced">{error}</div>}
      {message && <div className="success spaced">{message}</div>}

      {(canManage || canClaim) && <div className="actions spaced">
        {canManage && accident.vehicle_available_after_accident !== false && <button className="dangerButton" disabled={busy} onClick={() => void action("actions/mark-unavailable")}>{t("modules:accidents.markUnavailable")}</button>}
        {canClaim && !accident.claim && <button className="button" disabled={busy} onClick={() => setTab("claim")}>{t("modules:accidents.openClaim")}</button>}
        {canManage && accident.work_orders.length === 0 && <button className="button" disabled={busy || !repairEstimate} onClick={() => void action("actions/create-work-order", { estimated_damage_cost: repairEstimate })}>{t("modules:accidents.createWorkOrder")}</button>}
        {canClaim && accident.claim && accident.claim.claim_status !== "Closed" && <button className="secondaryButton" disabled={busy} onClick={() => void action("actions/close-claim")}>{t("modules:accidents.closeClaim")}</button>}
        {canManage && accident.status === "Resolved" && <button className="secondaryButton" disabled={busy} onClick={() => void action("actions/close")}>{t("modules:accidents.closeAccident")}</button>}
        {canManage && accident.status !== "Resolved" && accident.status !== "Closed" && <button className="secondaryButton" disabled={busy} onClick={() => void action("actions/resolve")}>{t("modules:accidents.resolveAccident")}</button>}
      </div>}

      <div className="vehicleTabs" role="tablist">
        {TABS.map((name) => <button key={name} className={`vehicleTab ${tab === name ? "active" : ""}`} onClick={() => setTab(name)}>{t(`modules:accidents.tabs.${name}`)}</button>)}
      </div>

      {tab === "summary" && <div className="detailGrid">
        <section className="card detailCard">
          <h2>{t("modules:accidents.accidentInformation")}</h2>
          <Details rows={[
            [t("common:labels.vehicle"), `${accident.brand} ${accident.model} · ${accident.license_plate}`],
            [t("common:labels.driver"), accident.driver_id ? <Link className="link" href={`/drivers/${accident.driver_id}`}>{accident.driver_name ?? `#${accident.driver_id}`}</Link> : "-"],
            [t("modules:accidents.assignmentId"), accident.assignment_id ? <Link className="link" href={`/vehicle-assignments/${accident.assignment_id}`}>#{accident.assignment_id}</Link> : "-"],
            [t("modules:accidents.reservationId"), accident.reservation_id ? `#${accident.reservation_id}` : "-"],
            [t("modules:accidents.accidentDate"), formatDateTime(accident.accident_datetime ?? accident.accident_date)],
            [t("common:labels.location"), accident.location],
            [t("modules:accidents.severity"), accident.severity],
            [t("common:labels.status"), accident.status],
            [t("common:labels.description"), accident.description ?? "-"]
          ]} />
        </section>
        <section className="card detailCard">
          <h2>{t("modules:accidents.assessment")}</h2>
          <Details rows={[
            [t("modules:accidents.vehicleAvailable"), accident.vehicle_available_after_accident ? t("common:labels.yes") : t("common:labels.no")],
            [t("modules:accidents.policeInvolved"), accident.police_involved ? t("common:labels.yes") : t("common:labels.no")],
            [t("modules:accidents.policeReport"), accident.police_report_number ?? "-"],
            [t("modules:accidents.estimatedDamage"), formatCurrency(accident.estimated_damage_cost)],
            [t("modules:accidents.actualDamage"), formatCurrency(accident.actual_damage_cost)],
            [t("modules:accidents.fault"), accident.fault_determination ?? "-"]
          ]} />
        </section>
      </div>}

      {tab === "people" && <div className="detailGrid">
        <section className="card detailCard"><h2>{t("modules:accidents.parties")}</h2>{accident.parties.length ? accident.parties.map((row) => <div className="linkedRecordCard" key={String(row.id)}><strong>{String(row.name)}</strong><span>{String(row.party_type)}</span><span className="muted">{String(row.phone ?? row.email ?? "")}</span></div>) : <p className="muted">{t("modules:accidents.noParties")}</p>}{canManage && <form className="form" onSubmit={addParty}><div className="formRow"><label>{t("common:labels.type")}</label><select className="select" value={party.party_type} onChange={(e) => setParty({ ...party, party_type: e.target.value })}>{["Third Party", "Passenger", "Witness", "Property Owner"].map((type) => <option key={type}>{type}</option>)}</select></div><div className="formRow"><label>{t("common:labels.name")}</label><input className="input" required value={party.name} onChange={(e) => setParty({ ...party, name: e.target.value })} /></div><div className="formRow"><label>{t("modules:accidents.phone")}</label><input className="input" value={party.phone} onChange={(e) => setParty({ ...party, phone: e.target.value })} /></div><button className="button" disabled={busy}>{t("modules:accidents.addParty")}</button></form>}</section>
        <section className="card detailCard"><h2>{t("modules:accidents.injuries")}</h2>{accident.injuries.length ? accident.injuries.map((row) => <div className="linkedRecordCard" key={String(row.id)}><strong>{String(row.injured_person_name)}</strong><span>{String(row.injury_severity)}</span><span className="muted">{String(row.description ?? "")}</span></div>) : <p className="muted">{t("modules:accidents.noInjuries")}</p>}{canManage && <form className="form" onSubmit={addInjury}><div className="formRow"><label>{t("modules:accidents.injuredPerson")}</label><input className="input" required value={injury.injured_person_name} onChange={(e) => setInjury({ ...injury, injured_person_name: e.target.value })} /></div><div className="formRow"><label>{t("modules:accidents.injurySeverity")}</label><select className="select" value={injury.injury_severity} onChange={(e) => setInjury({ ...injury, injury_severity: e.target.value })}>{["Minor", "Moderate", "Severe", "Critical"].map((severity) => <option key={severity}>{severity}</option>)}</select></div><div className="formRow"><label>{t("modules:accidents.partyId")}</label><input className="input" type="number" min="1" value={injury.party_id} onChange={(e) => setInjury({ ...injury, party_id: e.target.value })} /></div><button className="button" disabled={busy}>{t("modules:accidents.addInjury")}</button></form>}</section>
      </div>}

      {tab === "claim" && <section className="card detailCard">
        <h2>{t("modules:accidents.insuranceClaim")}</h2>
        {!accident.claim && !canClaim ? <p className="muted">{t("modules:accidents.noClaim")}</p> : <form className="form formGrid fullWidthForm" onSubmit={saveClaim}>
          <div className="formRow"><label>{t("modules:accidents.insuranceCompany")}</label><input className="input" required disabled={!canClaim || accident.claim?.claim_status === "Closed"} value={claim.insurance_company} onChange={(e) => setClaim({ ...claim, insurance_company: e.target.value })} /></div>
          <div className="formRow"><label>{t("modules:accidents.policyNumber")}</label><input className="input" required disabled={!canClaim || accident.claim?.claim_status === "Closed"} value={claim.policy_number} onChange={(e) => setClaim({ ...claim, policy_number: e.target.value })} /></div>
          <div className="formRow"><label>{t("modules:accidents.claimNumber")}</label><input className="input" required disabled={!canClaim || accident.claim?.claim_status === "Closed"} value={claim.claim_number} onChange={(e) => setClaim({ ...claim, claim_number: e.target.value })} /></div>
          <div className="formRow"><label>{t("common:labels.status")}</label><select className="select" disabled={!canClaim || accident.claim?.claim_status === "Closed"} value={claim.claim_status} onChange={(e) => setClaim({ ...claim, claim_status: e.target.value })}>{["Open", "Under Review", "Approved", "Settled", "Rejected"].map((status) => <option key={status}>{status}</option>)}</select></div>
          <div className="formRow"><label>{t("modules:accidents.claimOpened")}</label><input className="input" type="date" required disabled={!canClaim || accident.claim?.claim_status === "Closed"} value={claim.claim_opened_date} onChange={(e) => setClaim({ ...claim, claim_opened_date: e.target.value })} /></div>
          <div className="formRow"><label>{t("modules:accidents.insuranceDocumentId")}</label><input className="input" type="number" min="1" disabled={!canClaim || accident.claim?.claim_status === "Closed"} value={claim.insurance_document_id} onChange={(e) => setClaim({ ...claim, insurance_document_id: e.target.value })} /></div>
          <div className="formRow"><label>{t("modules:accidents.adjuster")}</label><input className="input" disabled={!canClaim || accident.claim?.claim_status === "Closed"} value={claim.adjuster_name} onChange={(e) => setClaim({ ...claim, adjuster_name: e.target.value })} /></div>
          <div className="formRow"><label>{t("modules:accidents.settlement")}</label><input className="input" type="number" min="0" step="0.01" disabled={!canClaim || accident.claim?.claim_status === "Closed"} value={claim.settlement_amount} onChange={(e) => setClaim({ ...claim, settlement_amount: e.target.value })} /></div>
          <div className="formRow"><label>{t("modules:accidents.deductible")}</label><input className="input" type="number" min="0" step="0.01" disabled={!canClaim || accident.claim?.claim_status === "Closed"} value={claim.deductible} onChange={(e) => setClaim({ ...claim, deductible: e.target.value })} /></div>
          <div className="formRow span2"><label>{t("common:labels.notes")}</label><textarea className="input textarea" disabled={!canClaim || accident.claim?.claim_status === "Closed"} value={claim.notes} onChange={(e) => setClaim({ ...claim, notes: e.target.value })} /></div>
          {canClaim && accident.claim?.claim_status !== "Closed" && <button className="button" disabled={busy}>{accident.claim ? t("common:actions.save") : t("modules:accidents.openClaim")}</button>}
        </form>}
      </section>}

      {tab === "repair" && <section className="card detailCard">
        <h2>{t("modules:accidents.repair")}</h2>
        {canManage && accident.work_orders.length === 0 && <div className="formRow spaced"><label>{t("modules:accidents.estimatedDamage")}</label><input className="input" type="number" min="0" step="0.01" value={repairEstimate} onChange={(e) => setRepairEstimate(e.target.value)} /><span className="muted">{t("modules:accidents.estimateBeforeWorkOrder")}</span></div>}
        {accident.work_orders.length ? accident.work_orders.map((order) => <div className="linkedRecordCard" key={order.id}><Link className="link" href={`/work-orders/${order.id}`}>{order.title}</Link><span>{order.status} · {formatCurrency(order.total_cost)}</span>{order.service && <Link className="link" href={`/services/${order.service.id}`}>{order.service.service_type} · {formatDate(order.service.service_date)}</Link>}</div>) : <p className="muted">{t("modules:accidents.noRepairs")}</p>}
      </section>}

      {tab === "attachments" && <section className="card detailCard">
        <h2>{t("modules:accidents.attachments")}</h2>
        {accident.attachments.map((file) => <button className="linkButton stackedLink" key={file.id} onClick={() => void apiDownloadFile(`/api/v1/files/${file.id}/download`, file.original_filename)}>{file.original_filename}</button>)}
        {accident.attachments.length === 0 && <p className="muted">{t("modules:accidents.noAttachments")}</p>}
        {canManage && <form className="actions" onSubmit={uploadAttachment}><input className="input" type="file" onChange={(e) => setUpload(e.target.files?.[0] ?? null)} /><button className="button" disabled={!upload || busy}>{t("modules:accidents.uploadAttachment")}</button></form>}
      </section>}

      {tab === "timeline" && <section className="card detailCard">
        <h2>{t("modules:accidents.timeline")}</h2>
        <div className="timeline">{accident.timeline.map((event) => <div className="timelineItem" key={event.id}><span className="timelineMarker" /><div className="timelineContent"><time>{formatDateTime(event.created_at)}</time><div className="timelineTitle"><strong>{event.action}</strong></div><p>{event.description}</p><span className="muted">{event.username}</span></div></div>)}</div>
      </section>}
    </section>
  );
}
