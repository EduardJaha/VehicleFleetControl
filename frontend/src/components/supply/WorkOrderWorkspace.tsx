"use client";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { apiDelete, apiPost, apiPostForm, apiPut, filesApi } from "@/lib/api";
import type { Attachment, WorkOrder } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import { CreateEntityDialog } from "@/components/ui/CreateEntityDialog";
import { MaintenanceTable } from "@/components/maintenance/Maintenance";
import {
  choices,
  emptyOptions,
  Fields,
  SupplyNotice,
  useSupplyData,
  type Field,
  type Options,
  type Row,
  type Values,
} from "./shared";

type Tab =
  | "Overview"
  | "Parts"
  | "Labor"
  | "Vendor Charges"
  | "Attachments"
  | "Timeline";
export function WorkOrderWorkspace({
  order,
  onChange,
  children,
}: {
  order: WorkOrder;
  onChange: () => Promise<unknown>;
  children: React.ReactNode;
}) {
  const { t } = useTranslation("modules");
  const text = (key: string) => t(`supply.${key}`);
  const { can } = useAuth();
  const { formatNumber, formatCurrency, formatDateTime } = useLanguage();
  const requestedTab = useSearchParams().get("tab");
  const [tab, setTab] = useState<Tab>(["Parts", "Labor", "Attachments"].includes(requestedTab || "") ? requestedTab as Tab : "Overview");
  const [mode, setMode] = useState<string | null>(null);
  const [values, setValues] = useState<Values>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [line, setLine] = useState<Row | null>(null);
  const base = `/work-orders/${order.id}`;
  const closed =
    order.archived ||
    ["Completed", "Cancelled"].includes(order.status) ||
    Boolean(order.linked_service);
  const parts = useSupplyData<Row[]>(`${base}/parts`, [], tab === "Parts");
  const labor = useSupplyData<Row[]>(`${base}/labor`, [], tab === "Labor");
  const assignments = useSupplyData<Row[]>(
    `${base}/technicians`,
    [],
    tab === "Labor",
  );
  const charges = useSupplyData<Row[]>(
    `${base}/vendor-charges`,
    [],
    tab === "Vendor Charges",
  );
  const attachments = useSupplyData<Attachment[]>(
    `/files?entity_type=WorkOrder&entity_id=${order.id}`,
    [],
    tab === "Attachments" || tab === "Vendor Charges",
  );
  const timeline = useSupplyData<Row[]>(
    `${base}/timeline`,
    [],
    tab === "Timeline",
  );
  const options = useSupplyData<Options>(
    "/supply-options",
    emptyOptions,
    can("inventory.manage") ||
      can("labor.manage") ||
      can("maintenance.assign_work_order") ||
      can("maintenance.manage_costs"),
  );
  const [file, setFile] = useState<File | null>(null);
  function start(next: string, row: Row | null = null) {
    setMode(next);
    setLine(row);
    setError(null);
    setValues({
      part_id: "",
      location_id: "",
      quantity: row
        ? String(Number(row.quantity) - Number(row.quantity_returned ?? 0))
        : "1",
      technician_id: "",
      actual_hours: "1",
      estimated_hours: "1",
      task_description: "",
      notes: "",
      vendor_id: String(order.vendor_id ?? ""),
      description: "",
      amount: "0",
      invoice_number: "",
      attachment_id: "",
      tax_amount: String(order.tax_amount ?? 0),
      discount_amount: String(order.discount_amount ?? 0),
      other_cost: String(order.other_cost ?? 0),
    });
  }
  async function refresh() {
    await Promise.all([
      parts.reload(),
      labor.reload(),
      assignments.reload(),
      charges.reload(),
      attachments.reload(),
      timeline.reload(),
      onChange(),
    ]);
  }
  async function run(action: () => Promise<unknown>, close = false) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await action();
      if (close) setMode(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function save(e: React.FormEvent) {
    e.preventDefault();
    await run(async () => {
      if (mode === "issue")
        return apiPost(`${base}/parts`, {
          part_id: Number(values.part_id),
          location_id: Number(values.location_id),
          quantity: values.quantity,
          notes: values.notes || null,
        });
      if (mode === "return")
        return apiPost(`${base}/parts/${line?.id}/return`, {
          quantity: values.quantity,
          notes: values.notes || null,
        });
      if (mode === "manual")
        return apiPost(`${base}/labor`, {
          technician_id: Number(values.technician_id),
          actual_hours: values.actual_hours,
          task_description: values.task_description || null,
          notes: values.notes || null,
        });
      if (mode === "clockIn")
        return apiPost(`${base}/labor/clock-in`, {
          technician_id: Number(values.technician_id),
          task_description: values.task_description || null,
          notes: values.notes || null,
        });
      if (mode === "assign")
        return apiPost(`${base}/technicians`, {
          technician_id: Number(values.technician_id),
          estimated_hours: values.estimated_hours,
          task_description: values.task_description || null,
        });
      if (mode === "charge")
        return apiPost(`${base}/vendor-charges`, {
          vendor_id: Number(values.vendor_id),
          description: values.description,
          amount: values.amount,
          invoice_number: values.invoice_number || null,
          attachment_id: values.attachment_id
            ? Number(values.attachment_id)
            : null,
        });
      return apiPut(`${base}/cost-adjustments`, {
        vendor_id: values.vendor_id ? Number(values.vendor_id) : null,
        tax_amount: values.tax_amount,
        discount_amount: values.discount_amount,
        other_cost: values.other_cost,
      });
    }, true);
  }
  const techField: Field = {
    key: "technician_id",
    type: "select",
    required: true,
    options: choices(options.data.technicians),
  };
  const fields: Field[] =
    mode === "issue"
      ? [
          {
            key: "part_id",
            type: "select",
            required: true,
            options: choices(options.data.parts),
          },
          {
            key: "location_id",
            type: "select",
            required: true,
            options: choices(options.data.locations),
          },
          {
            key: "quantity",
            type: "number",
            min: "0.001",
            step: "0.001",
            required: true,
          },
          { key: "notes" },
        ]
      : mode === "return"
        ? [
            {
              key: "quantity",
              type: "number",
              min: "0.001",
              max: String(
                Number(line?.quantity) - Number(line?.quantity_returned ?? 0),
              ),
              step: "0.001",
              required: true,
            },
            { key: "notes" },
          ]
        : mode === "manual"
          ? [
              techField,
              {
                key: "actual_hours",
                type: "number",
                required: true,
                min: "0.01",
                step: "0.01",
              },
              { key: "task_description" },
              { key: "notes" },
            ]
          : mode === "clockIn"
            ? [techField, { key: "task_description" }, { key: "notes" }]
            : mode === "assign"
              ? [
                  techField,
                  {
                    key: "estimated_hours",
                    type: "number",
                    min: "0",
                    step: "0.01",
                    required: true,
                  },
                  { key: "task_description" },
                ]
              : mode === "charge"
                ? [
                    {
                      key: "vendor_id",
                      type: "select",
                      required: true,
                      options: choices(options.data.vendors),
                    },
                    { key: "description", required: true },
                    {
                      key: "amount",
                      type: "number",
                      min: "0",
                      step: "0.01",
                      required: true,
                    },
                    { key: "invoice_number" },
                    {
                      key: "attachment_id",
                      type: "select",
                      options: attachments.data.map((x) => ({
                        value: String(x.id),
                        label: x.original_filename,
                      })),
                    },
                  ]
                : [
                    {
                      key: "vendor_id",
                      type: "select",
                      options: choices(options.data.vendors),
                    },
                    {
                      key: "other_cost",
                      type: "number",
                      min: "0",
                      step: "0.01",
                      required: true,
                    },
                    {
                      key: "tax_amount",
                      type: "number",
                      min: "0",
                      step: "0.01",
                      required: true,
                    },
                    {
                      key: "discount_amount",
                      type: "number",
                      min: "0",
                      step: "0.01",
                      required: true,
                    },
                  ];
  return (
    <>
      <div
        className="maintenanceTabs spaced"
        role="tablist"
        aria-label={text("workOrderTabs")}
      >
        {(
          [
            "Overview",
            "Parts",
            "Labor",
            "Vendor Charges",
            "Attachments",
            "Timeline",
          ] as Tab[]
        ).map((name) => (
          <button
            role="tab"
            aria-selected={tab === name}
            aria-controls="work-order-tab-panel"
            className={`maintenanceTab ${tab === name ? "active" : ""}`}
            key={name}
            onClick={() => {
              setTab(name);
              setError(null);
            }}
          >
            {text(name)}
          </button>
        ))}
      </div>
      <SupplyNotice error={mode ? null : error} />
      <div id="work-order-tab-panel" role="tabpanel">
        {tab === "Overview" && (
          <>
            {!closed && can("maintenance.manage_costs") && (
              <div className="actions spaced">
                <button
                  className="secondaryButton"
                  onClick={() => start("adjustCosts")}
                >
                  {text("adjustCosts")}
                </button>
              </div>
            )}
            {children}
          </>
        )}
        {tab === "Parts" && (
          <section className="card spaced">
            <div className="header">
              <h2>{text("Parts")}</h2>
              {!closed && can("inventory.manage") && (
                <button className="button" onClick={() => start("issue")}>
                  {text("issue")}
                </button>
              )}
            </div>
            <SupplyNotice error={parts.error} loading={parts.loading} />
            <MaintenanceTable>
              <thead>
                <tr>
                  {[
                    "part_id",
                    "location_id",
                    "quantity",
                    "quantity_returned",
                    "unit_cost",
                    "line_total",
                    "actions",
                  ].map((k) => (
                    <th key={k}>{text(k)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {parts.data.map((r) => (
                  <tr key={r.id}>
                    <td>
                      {String(r.part_number)} — {String(r.part_name)}
                    </td>
                    <td>
                      {options.data.locations.find(
                        (l) => l.id === r.location_id,
                      )?.name ?? `#${r.location_id}`}
                    </td>
                    <td>{formatNumber(Number(r.quantity))}</td>
                    <td>{formatNumber(Number(r.quantity_returned))}</td>
                    <td>{formatCurrency(Number(r.unit_cost))}</td>
                    <td>{formatCurrency(Number(r.total_cost))}</td>
                    <td>
                      {!closed && can("inventory.manage") && (
                        <button
                          className="secondaryButton smallButton"
                          onClick={() => start("return", r)}
                        >
                          {text("return")}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </MaintenanceTable>
            {!parts.data.length && <p className="muted">{text("empty")}</p>}
          </section>
        )}
        {tab === "Labor" && (
          <section className="card spaced">
            <div className="header">
              <h2>{text("Labor")}</h2>
              <div className="actions">
                {!closed && can("maintenance.assign_work_order") && (
                  <button
                    className="secondaryButton"
                    onClick={() => start("assign")}
                  >
                    {text("assign")}
                  </button>
                )}
                {!closed && can("labor.manage") && (
                  <>
                    <button
                      className="secondaryButton"
                      onClick={() => start("manual")}
                    >
                      {text("manual")}
                    </button>
                    <button className="button" onClick={() => start("clockIn")}>
                      {text("clockIn")}
                    </button>
                  </>
                )}
              </div>
            </div>
            <SupplyNotice
              error={labor.error ?? assignments.error}
              loading={labor.loading}
            />
            {assignments.data.length > 0 && (
              <div className="spaced">
                <h3>{text("assignments")}</h3>
                {assignments.data.map((r) => (
                  <p key={r.id}>
                    {String(r.technician_name)} · {text("estimated_hours")}:{" "}
                    {formatNumber(Number(r.estimated_hours))} ·{" "}
                    {String(r.task_description ?? "")}
                  </p>
                ))}
              </div>
            )}
            <MaintenanceTable>
              <thead>
                <tr>
                  {[
                    "technician_id",
                    "task_description",
                    "clock_in",
                    "clock_out",
                    "actual_hours",
                    "hourly_rate",
                    "labor_cost",
                    "actions",
                  ].map((k) => (
                    <th key={k}>{text(k)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {labor.data.map((r) => (
                  <tr key={r.id}>
                    <td>{String(r.technician_name)}</td>
                    <td>{String(r.task_description ?? "—")}</td>
                    <td>
                      {r.clock_in ? formatDateTime(String(r.clock_in)) : "—"}
                    </td>
                    <td>
                      {r.clock_out ? (
                        formatDateTime(String(r.clock_out))
                      ) : r.clock_in ? (
                        <span className="warningBadge">
                          {text("clockActive")}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>{formatNumber(Number(r.actual_hours))}</td>
                    <td>{formatCurrency(Number(r.hourly_rate))}</td>
                    <td>{formatCurrency(Number(r.labor_cost))}</td>
                    <td>
                      {!closed &&
                        can("labor.manage") &&
                        (r.clock_in && !r.clock_out ? (
                          <button
                            className="button smallButton"
                            disabled={busy}
                            onClick={() =>
                              void run(() =>
                                apiPost(`${base}/labor/${r.id}/clock-out`, {}),
                              )
                            }
                          >
                            {text("clockOut")}
                          </button>
                        ) : (
                          <button
                            className="secondaryButton smallButton"
                            disabled={busy}
                            onClick={() =>
                              void run(() => apiDelete(`${base}/labor/${r.id}`))
                            }
                          >
                            {text("archive")}
                          </button>
                        ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </MaintenanceTable>
            {!labor.data.length && <p className="muted">{text("empty")}</p>}
          </section>
        )}
        {tab === "Vendor Charges" && (
          <section className="card spaced">
            <div className="header">
              <h2>{text("Vendor Charges")}</h2>
              {!closed && can("maintenance.manage_costs") && (
                <button className="button" onClick={() => start("charge")}>
                  {text("charge")}
                </button>
              )}
            </div>
            <SupplyNotice error={charges.error} loading={charges.loading} />
            <MaintenanceTable>
              <thead>
                <tr>
                  {[
                    "vendor_id",
                    "description",
                    "invoice_number",
                    "amount",
                    "attachment_id",
                    "actions",
                  ].map((k) => (
                    <th key={k}>{text(k)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {charges.data.map((r) => (
                  <tr key={r.id}>
                    <td>{String(r.vendor_name)}</td>
                    <td>{String(r.description)}</td>
                    <td>{String(r.invoice_number ?? "—")}</td>
                    <td>{formatCurrency(Number(r.amount))}</td>
                    <td>
                      {r.attachment_id ? (
                        <button
                          className="secondaryButton smallButton"
                          onClick={() => setTab("Attachments")}
                        >
                          #{String(r.attachment_id)}
                        </button>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      {!closed && can("maintenance.manage_costs") && (
                        <button
                          className="secondaryButton smallButton"
                          disabled={busy}
                          onClick={() =>
                            void run(() =>
                              apiDelete(`${base}/vendor-charges/${r.id}`),
                            )
                          }
                        >
                          {text("archive")}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </MaintenanceTable>
            {!charges.data.length && <p className="muted">{text("empty")}</p>}
          </section>
        )}
        {tab === "Attachments" && (
          <section className="card spaced">
            <h2>{text("Attachments")}</h2>
            <SupplyNotice
              error={attachments.error}
              loading={attachments.loading}
            />
            {can("maintenance.assign_work_order") && !order.archived && (
              <form
                className="actions spaced"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!file) return;
                  const data = new FormData();
                  data.append("entity_type", "WorkOrder");
                  data.append("entity_id", String(order.id));
                  data.append("file", file);
                  void run(async () => {
                    await apiPostForm("/files", data);
                    setFile(null);
                  });
                }}
              >
                <label>
                  {text("file")}{" "}
                  <input
                    type="file"
                    required
                    onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  />
                </label>
                <button className="button" disabled={busy || !file}>
                  {text("upload")}
                </button>
              </form>
            )}
            {attachments.data.map((f) => (
              <div className="actions spaced" key={f.id}>
                <span>
                  #{f.id} · {f.original_filename} ·{" "}
                  {formatDateTime(f.uploaded_at)}
                </span>
                <button
                  className="secondaryButton smallButton"
                  onClick={() => void run(() => filesApi.download(f))}
                >
                  {text("download")}
                </button>
              </div>
            ))}
            {!attachments.data.length && (
              <p className="muted">{text("empty")}</p>
            )}
          </section>
        )}
        {tab === "Timeline" && (
          <section className="card spaced">
            <h2>{text("Timeline")}</h2>
            <SupplyNotice error={timeline.error} loading={timeline.loading} />
            <div className="timeline">
              {timeline.data.map((r) => (
                <article className="timelineItem" key={r.id}>
                  <div className="timelineMarker" />
                  <div className="timelineContent">
                    <time>{formatDateTime(String(r.created_at))}</time>
                    <strong>
                      {t(`modules:supplyEvents.${String(r.action)}`, {
                        defaultValue: String(r.action),
                      })}
                    </strong>
                    <span className="muted">{String(r.actor ?? "—")}</span>
                  </div>
                </article>
              ))}
            </div>
            {!timeline.data.length && <p className="muted">{text("empty")}</p>}
          </section>
        )}
      </div>
      <CreateEntityDialog
        open={Boolean(mode)}
        title={text(mode ?? "edit")}
        busy={busy}
        onClose={() => setMode(null)}
      >
        <form className="form" onSubmit={save}>
          <SupplyNotice error={error ?? options.error} />
          <Fields fields={fields} values={values} setValues={setValues} />
          <button className="button" disabled={busy}>
            {text("save")}
          </button>
        </form>
      </CreateEntityDialog>
    </>
  );
}
