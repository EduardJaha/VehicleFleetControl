"use client";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { apiPost, apiPut } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import {
  MaintenancePageHeader,
  MaintenanceTable,
  MaintenanceStatusBadge,
} from "@/components/maintenance/Maintenance";
import { CreateEntityDialog } from "@/components/ui/CreateEntityDialog";
import {
  Fields,
  choices,
  emptyOptions,
  SupplyNotice,
  useSupplyData,
  type Options,
  type Values,
} from "@/components/supply/shared";

type Item = {
  id: number;
  part_id: number;
  part_number: string;
  part_name: string;
  quantity_ordered: string;
  quantity_received: string;
  unit_cost: string;
  line_total: string;
};
type PO = {
  id: number;
  order_number: string;
  vendor_id: number;
  vendor_name: string;
  storage_location_id: number;
  status: string;
  order_date: string | null;
  expected_date: string | null;
  tax_amount: string;
  discount_amount: string;
  total_amount: string;
  notes: string | null;
  archived: boolean;
  items: Item[];
};
type DraftLine = {
  part_id: string;
  quantity_ordered: string;
  unit_cost: string;
};
const blankLine = (): DraftLine => ({
  part_id: "",
  quantity_ordered: "1",
  unit_cost: "0",
});
export default function PurchaseOrdersPage() {
  const { t } = useTranslation("modules");
  const text = (key: string) => t(`supply.${key}`);
  const { can } = useAuth();
  const { formatCurrency, formatDate, formatNumber } = useLanguage();
  const canCreate = can("purchase_orders.create"),
    canApprove = can("purchase_orders.approve"),
    canReceive = can("inventory.manage");
  const [statusFilter, setStatusFilter] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const orders = useSupplyData<PO[]>(
    `/purchase-orders?include_archived=${showArchived}${statusFilter ? `&status=${encodeURIComponent(statusFilter)}` : ""}`,
    [],
    can("purchase_orders.view"),
  );
  const options = useSupplyData<Options>(
    "/supply-options",
    emptyOptions,
    can("purchase_orders.view"),
  );
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<PO | null>(null);
  const [receipt, setReceipt] = useState<PO | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [values, setValues] = useState<Values>({});
  const [lines, setLines] = useState<DraftLine[]>([blankLine()]);
  const statuses = [
    "Draft",
    "Submitted",
    "Approved",
    "Ordered",
    "Partially Received",
    "Received",
    "Cancelled",
  ];
  function edit(order: PO | null) {
    setEditing(order);
    setReceipt(null);
    setError(null);
    setValues({
      order_number: order?.order_number ?? "",
      vendor_id: String(order?.vendor_id ?? ""),
      storage_location_id: String(order?.storage_location_id ?? ""),
      order_date:
        order?.order_date?.slice(0, 10) ??
        new Date().toISOString().slice(0, 10),
      expected_date: order?.expected_date?.slice(0, 10) ?? "",
      tax_amount: String(order?.tax_amount ?? 0),
      discount_amount: String(order?.discount_amount ?? 0),
      notes: order?.notes ?? "",
    });
    setLines(
      order?.items.map((i) => ({
        part_id: String(i.part_id),
        quantity_ordered: String(i.quantity_ordered),
        unit_cost: String(i.unit_cost),
      })) ?? [blankLine()],
    );
    setOpen(true);
  }
  function receive(order: PO) {
    setReceipt(order);
    setEditing(null);
    setError(null);
    setValues({
      storage_location_id: String(order.storage_location_id),
      notes: "",
      ...Object.fromEntries(order.items.map((i) => [`item_${i.id}`, "0"])),
    });
    setOpen(true);
  }
  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (receipt)
        await apiPost(`/purchase-orders/${receipt.id}/receive`, {
          storage_location_id: Number(values.storage_location_id),
          notes: values.notes || null,
          items: receipt.items
            .filter((i) => Number(values[`item_${i.id}`]) > 0)
            .map((i) => ({ item_id: i.id, quantity: values[`item_${i.id}`] })),
        });
      else {
        const payload = {
          ...values,
          vendor_id: Number(values.vendor_id),
          storage_location_id: Number(values.storage_location_id),
          order_date: values.order_date
            ? `${values.order_date}T00:00:00`
            : null,
          expected_date: values.expected_date
            ? `${values.expected_date}T00:00:00`
            : null,
          status: "Draft",
          items: lines.map((i) => ({ ...i, part_id: Number(i.part_id) })),
        };
        if (editing) await apiPut(`/purchase-orders/${editing.id}`, payload);
        else await apiPost("/purchase-orders", payload);
      }
      setOpen(false);
      await orders.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function change(order: PO, next: string) {
    setBusy(true);
    orders.setError(null);
    try {
      if (next === "archive")
        await apiPut(`/purchase-orders/${order.id}/archive`, {});
      else if (next === "restore")
        await apiPost(`/purchase-orders/${order.id}/restore`, {});
      else
        await apiPut(`/purchase-orders/${order.id}/status`, { status: next });
      await orders.reload();
    } catch (e) {
      orders.setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  if (!can("purchase_orders.view"))
    return <p className="card">{text("noPermission")}</p>;
  return (
    <section>
      <MaintenancePageHeader
        title={text("purchase-orders")}
        description={text("purchase-ordersDescription")}
        actions={
          canCreate && (
            <button className="button" onClick={() => edit(null)}>
              {text("add")}
            </button>
          )
        }
      />
      <div className="actions spaced">
        <label>
          {text("status")}{" "}
          <select
            className="select"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="">{text("all")}</option>
            {statuses.map((s) => (
              <option key={s} value={s}>
                {text(s)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
          />{" "}
          {text("includeArchived")}
        </label>
      </div>
      <SupplyNotice
        error={orders.error ?? options.error}
        loading={orders.loading}
      />
      {orders.data.map((order) => (
        <article className="card spaced" key={order.id}>
          <div className="header">
            <div>
              <h2>
                {order.order_number}{" "}
                <MaintenanceStatusBadge
                  status={order.archived ? "Archived" : order.status}
                />
              </h2>
              <p className="muted">
                {order.vendor_name} · {text("expected_date")}:{" "}
                {order.expected_date ? formatDate(order.expected_date) : "—"}
              </p>
            </div>
            <strong>{formatCurrency(order.total_amount)}</strong>
          </div>
          <MaintenanceTable>
            <thead>
              <tr>
                {[
                  "part_id",
                  "quantity_ordered",
                  "quantity_received",
                  "unit_cost",
                  "line_total",
                ].map((k) => (
                  <th key={k}>{text(k)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {order.items.map((i) => (
                <tr key={i.id}>
                  <td>
                    {i.part_number} — {i.part_name}
                  </td>
                  <td>{formatNumber(Number(i.quantity_ordered))}</td>
                  <td>{formatNumber(Number(i.quantity_received))}</td>
                  <td>{formatCurrency(i.unit_cost)}</td>
                  <td>{formatCurrency(i.line_total)}</td>
                </tr>
              ))}
            </tbody>
          </MaintenanceTable>
          <div className="actions spaced">
            {!order.archived && (
              <>
                {canCreate && order.status === "Draft" && (
                  <>
                    <button
                      className="secondaryButton"
                      disabled={busy}
                      onClick={() => edit(order)}
                    >
                      {text("edit")}
                    </button>
                    <button
                      className="button"
                      disabled={busy}
                      onClick={() => void change(order, "Submitted")}
                    >
                      {text("submit")}
                    </button>
                  </>
                )}
                {canApprove && order.status === "Submitted" && (
                  <button
                    className="button"
                    disabled={busy}
                    onClick={() => void change(order, "Approved")}
                  >
                    {text("approve")}
                  </button>
                )}
                {canCreate && order.status === "Approved" && (
                  <button
                    className="secondaryButton"
                    disabled={busy}
                    onClick={() => void change(order, "Ordered")}
                  >
                    {text("markOrdered")}
                  </button>
                )}
                {canReceive &&
                  ["Approved", "Ordered", "Partially Received"].includes(
                    order.status,
                  ) && (
                    <button
                      className="button"
                      disabled={busy}
                      onClick={() => receive(order)}
                    >
                      {text("receive")}
                    </button>
                  )}
                {canCreate &&
                  !["Received", "Cancelled"].includes(order.status) && (
                    <button
                      className="secondaryButton"
                      disabled={busy}
                      onClick={() => void change(order, "Cancelled")}
                    >
                      {text("cancelOrder")}
                    </button>
                  )}
              </>
            )}
            {canCreate &&
              (order.archived ||
                ["Received", "Cancelled"].includes(order.status)) && (
                <button
                  className="secondaryButton"
                  disabled={busy}
                  onClick={() =>
                    void change(order, order.archived ? "restore" : "archive")
                  }
                >
                  {text(order.archived ? "restore" : "archive")}
                </button>
              )}
          </div>
        </article>
      ))}
      {!orders.data.length && !orders.loading && (
        <p className="card muted">{text("empty")}</p>
      )}
      <CreateEntityDialog
        open={open}
        title={text(receipt ? "receive" : editing ? "edit" : "newOrder")}
        busy={busy}
        onClose={() => setOpen(false)}
      >
        <form className="form" onSubmit={save}>
          <SupplyNotice error={error} />
          <Fields
            fields={
              receipt
                ? [
                    {
                      key: "storage_location_id",
                      type: "select",
                      required: true,
                      options: choices(options.data.locations),
                    },
                    { key: "notes" },
                  ]
                : [
                    { key: "order_number", required: true },
                    {
                      key: "vendor_id",
                      type: "select",
                      required: true,
                      options: choices(options.data.vendors),
                    },
                    {
                      key: "storage_location_id",
                      type: "select",
                      required: true,
                      options: choices(options.data.locations),
                    },
                    { key: "order_date", type: "date" },
                    { key: "expected_date", type: "date" },
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
                    { key: "notes", type: "textarea" },
                  ]
            }
            values={values}
            setValues={setValues}
          />
          {receipt ? (
            <>
              <p className="muted">{text("receiptHelp")}</p>
              {receipt.items.map((i) => (
                <label className="supplyField" key={i.id}>
                  {i.part_number} — {i.part_name} ({text("remaining")}:{" "}
                  {formatNumber(
                    Number(i.quantity_ordered) - Number(i.quantity_received),
                  )}
                  )
                  <input
                    className="input"
                    type="number"
                    min="0"
                    max={
                      Number(i.quantity_ordered) - Number(i.quantity_received)
                    }
                    step="0.001"
                    value={String(values[`item_${i.id}`])}
                    onChange={(e) =>
                      setValues({ ...values, [`item_${i.id}`]: e.target.value })
                    }
                  />
                </label>
              ))}
            </>
          ) : (
            <>
              {lines.map((line, index) => (
                <div className="card form" key={index}>
                  <Fields
                    fields={[
                      {
                        key: "part_id",
                        type: "select",
                        required: true,
                        options: choices(options.data.parts),
                      },
                      {
                        key: "quantity_ordered",
                        type: "number",
                        required: true,
                        min: "0.001",
                        step: "0.001",
                      },
                      {
                        key: "unit_cost",
                        type: "number",
                        required: true,
                        min: "0",
                        step: "0.0001",
                      },
                    ]}
                    values={line}
                    setValues={(next) => {
                      const updated = { ...next } as DraftLine;
                      if (next.part_id !== line.part_id)
                        updated.unit_cost = String(
                          options.data.parts.find(
                            (p) => p.id === Number(next.part_id),
                          )?.unit_cost ?? 0,
                        );
                      setLines(
                        lines.map((l, n) => (n === index ? updated : l)),
                      );
                    }}
                  />
                  {lines.length > 1 && (
                    <button
                      className="secondaryButton smallButton"
                      type="button"
                      onClick={() =>
                        setLines(lines.filter((_, n) => n !== index))
                      }
                    >
                      {text("removeLine")}
                    </button>
                  )}
                </div>
              ))}
              <button
                className="secondaryButton"
                type="button"
                onClick={() => setLines([...lines, blankLine()])}
              >
                {text("addLine")}
              </button>
            </>
          )}
          <button
            className="button"
            disabled={
              busy ||
              Boolean(
                receipt &&
                  !receipt.items.some(
                    (i) => Number(values[`item_${i.id}`]) > 0,
                  ),
              )
            }
          >
            {text(receipt ? "receive" : "save")}
          </button>
        </form>
      </CreateEntityDialog>
    </section>
  );
}
