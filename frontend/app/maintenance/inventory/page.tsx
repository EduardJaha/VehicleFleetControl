"use client";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { apiPost, apiPut } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import { CreateEntityDialog } from "@/components/ui/CreateEntityDialog";
import {
  MaintenancePageHeader,
  MaintenanceTable,
} from "@/components/maintenance/Maintenance";
import {
  Fields,
  choices,
  emptyOptions,
  SupplyNotice,
  useSupplyData,
  type Options,
  type Row,
  type Values,
  type Field,
} from "@/components/supply/shared";

export default function InventoryPage() {
  const { t } = useTranslation("modules");
  const text = (key: string) => t(`supply.${key}`);
  const { can } = useAuth();
  const { formatNumber, formatCurrency, formatDateTime } = useLanguage();
  const [location, setLocation] = useState("");
  const [low, setLow] = useState(false);
  const stock = useSupplyData<Row[]>(
    `/inventory?low_stock_only=${low}${location ? `&location_id=${location}` : ""}`,
    [],
    can("inventory.view"),
  );
  const ledger = useSupplyData<Row[]>(
    `/inventory-transactions${location ? `?location_id=${location}` : ""}`,
    [],
    can("inventory.view"),
  );
  const options = useSupplyData<Options>(
    "/supply-options",
    emptyOptions,
    can("inventory.view"),
  );
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [values, setValues] = useState<Values>({});
  function start(row: Row | null = null) {
    setSettings(row);
    setError(null);
    setValues(
      row
        ? {
            minimum_stock: String(row.minimum_stock),
            reserved_quantity: String(row.reserved_quantity),
          }
        : {
            part_id: "",
            transaction_type: "Opening Balance",
            quantity: "1",
            from_location_id: "",
            to_location_id: location,
            notes: "",
          },
    );
    setOpen(true);
  }
  const kind = String(values.transaction_type);
  const incoming = [
    "Purchase",
    "Opening Balance",
    "Adjustment",
    "Transfer",
  ].includes(kind);
  const outgoing = ["Write-Off", "Transfer"].includes(kind);
  const fields: Field[] = settings
    ? [
        { key: "minimum_stock", type: "number", min: "0", step: "0.001" },
        {
          key: "reserved_quantity",
          type: "number",
          min: "0",
          step: "0.001",
          required: true,
        },
      ]
    : [
        {
          key: "part_id",
          type: "select",
          required: true,
          options: choices(options.data.parts),
        },
        {
          key: "transaction_type",
          type: "select",
          required: true,
          options: [
            "Opening Balance",
            "Purchase",
            "Transfer",
            "Adjustment",
            "Write-Off",
          ].map((x) => ({ value: x, label: text(x) })),
        },
        {
          key: "quantity",
          type: "number",
          required: true,
          step: "0.001",
          min: kind === "Adjustment" ? undefined : "0.001",
        },
        ...(outgoing
          ? [
              {
                key: "from_location_id",
                type: "select" as const,
                required: true,
                options: choices(options.data.locations),
              },
            ]
          : []),
        ...(incoming
          ? [
              {
                key: "to_location_id",
                type: "select" as const,
                required: true,
                options: choices(options.data.locations),
              },
            ]
          : []),
        { key: "notes", type: "textarea" },
      ];
  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (settings)
        await apiPut(`/inventory/${settings.part_id}/${settings.location_id}`, {
          reserved_quantity: values.reserved_quantity,
          minimum_stock: values.minimum_stock || null,
        });
      else
        await apiPost("/inventory-transactions", {
          part_id: Number(values.part_id),
          transaction_type: kind,
          quantity: values.quantity,
          from_location_id: outgoing ? Number(values.from_location_id) : null,
          to_location_id: incoming ? Number(values.to_location_id) : null,
          notes: values.notes || null,
        });
      setOpen(false);
      await Promise.all([stock.reload(), ledger.reload()]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  const name = (group: keyof Options, id: unknown) =>
    options.data[group].find((r) => r.id === Number(id))?.name ??
    (id ? `#${id}` : "—");
  if (!can("inventory.view"))
    return <p className="card">{text("noPermission")}</p>;
  return (
    <section>
      <MaintenancePageHeader
        title={text("inventory")}
        description={text("inventoryDescription")}
        actions={
          can("inventory.manage") && (
            <button className="button" onClick={() => start()}>
              {text("recordMovement")}
            </button>
          )
        }
      />
      <div className="card form spaced">
        <div className="formGrid">
          <label className="supplyField">
            {text("location_id")}
            <select
              className="select"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
            >
              <option value="">{text("all")}</option>
              {options.data.locations.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <input
              type="checkbox"
              checked={low}
              onChange={(e) => setLow(e.target.checked)}
            />{" "}
            {text("lowStockOnly")}
          </label>
          <div>
            <span className="muted">{text("inventoryValue")}</span>
            <h2>
              {formatCurrency(
                stock.data.reduce(
                  (sum, r) => sum + Number(r.inventory_value),
                  0,
                ),
              )}
            </h2>
          </div>
        </div>
      </div>
      <SupplyNotice
        error={stock.error ?? ledger.error ?? options.error}
        loading={stock.loading}
      />
      <div className="card spaced">
        <MaintenanceTable>
          <thead>
            <tr>
              {[
                "part_number",
                "name",
                "location_id",
                "quantity_on_hand",
                "reserved_quantity",
                "available_quantity",
                "minimum_stock",
                "inventoryValue",
                "actions",
              ].map((k) => (
                <th key={k}>{text(k)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {stock.data.map((row) => (
              <tr key={row.id}>
                <td>{String(row.part_number)}</td>
                <td>
                  {String(row.part_name)}{" "}
                  {row.low_stock ? (
                    <span className="warningBadge">{text("lowStock")}</span>
                  ) : null}
                </td>
                <td>{String(row.location_name)}</td>
                {[
                  "quantity_on_hand",
                  "reserved_quantity",
                  "available_quantity",
                  "minimum_stock",
                ].map((k) => (
                  <td key={k}>{formatNumber(Number(row[k]))}</td>
                ))}
                <td>{formatCurrency(Number(row.inventory_value))}</td>
                <td>
                  {can("inventory.manage") && (
                    <button
                      className="secondaryButton smallButton"
                      onClick={() => start(row)}
                    >
                      {text("reserveThreshold")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </MaintenanceTable>
        {!stock.data.length && <p className="muted">{text("empty")}</p>}
      </div>
      <div className="card spaced">
        <h2>{text("transactions")}</h2>
        <MaintenanceTable>
          <thead>
            <tr>
              {[
                "date",
                "part_id",
                "transaction_type",
                "quantity",
                "from_location_id",
                "to_location_id",
                "notes",
              ].map((k) => (
                <th key={k}>{text(k)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ledger.data.map((row) => (
              <tr key={row.id}>
                <td>{formatDateTime(String(row.created_at))}</td>
                <td>{name("parts", row.part_id)}</td>
                <td>{text(String(row.transaction_type))}</td>
                <td>{formatNumber(Number(row.quantity))}</td>
                <td>{name("locations", row.from_location_id)}</td>
                <td>{name("locations", row.to_location_id)}</td>
                <td>{String(row.notes ?? "—")}</td>
              </tr>
            ))}
          </tbody>
        </MaintenanceTable>
        {!ledger.data.length && <p className="muted">{text("empty")}</p>}
      </div>
      <CreateEntityDialog
        open={open}
        title={text(settings ? "reserveThreshold" : "recordMovement")}
        busy={busy}
        onClose={() => setOpen(false)}
      >
        <form className="form" onSubmit={save}>
          <SupplyNotice error={error} />
          <Fields fields={fields} values={values} setValues={setValues} />
          {kind === "Adjustment" && (
            <p className="muted">{text("adjustmentHelp")}</p>
          )}
          <button className="button" disabled={busy}>
            {text("save")}
          </button>
        </form>
      </CreateEntityDialog>
    </section>
  );
}
