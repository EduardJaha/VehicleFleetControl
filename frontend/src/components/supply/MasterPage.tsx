"use client";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { apiDelete, apiPost, apiPut } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLanguage } from "@/components/i18n/LanguageProvider";
import { CreateEntityDialog } from "@/components/ui/CreateEntityDialog";
import {
  MaintenancePageHeader,
  MaintenanceTable,
  MaintenanceStatusBadge,
} from "@/components/maintenance/Maintenance";
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

const vendorTypes = [
  "Workshop",
  "Parts Supplier",
  "Fuel Station",
  "Charging Provider",
  "Insurance Company",
  "Tire Supplier",
  "Towing Company",
  "Vehicle Dealer",
  "Other",
];
export function MasterPage({
  kind,
}: {
  kind: "vendors" | "parts" | "technicians" | "part-categories";
}) {
  const { t } = useTranslation(["modules", "common"]);
  const { can } = useAuth();
  const { formatCurrency, formatNumber } = useLanguage();
  const permission = kind === "part-categories" ? "parts" : kind;
  const canWrite = can(`${permission}.manage`);
  const [search, setSearch] = useState("");
  const [archived, setArchived] = useState(false);
  const [category, setCategory] = useState("");
  const [vendor, setVendor] = useState("");
  const query = new URLSearchParams({
    include_archived: String(archived),
    ...(kind === "parts"
      ? {
          search,
          ...(category ? { category_id: category } : {}),
          ...(vendor ? { vendor_id: vendor } : {}),
        }
      : {}),
  });
  const { data, error, setError, loading, reload } = useSupplyData<Row[]>(
    `/${kind}?${query}`,
    [],
    can(`${permission}.view`),
  );
  const options = useSupplyData<Options>(
    "/supply-options",
    emptyOptions,
    kind === "parts",
  );
  const [editing, setEditing] = useState<Row | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [values, setValues] = useState<Values>({});
  const [dialogError, setDialogError] = useState<string | null>(null);
  const text = (key: string) => t(`modules:supply.${key}`);
  const fields: Field[] =
    kind === "vendors"
      ? [
          { key: "name", required: true },
          {
            key: "vendor_type",
            type: "select",
            required: true,
            options: vendorTypes.map((x) => ({ value: x, label: text(x) })),
          },
          { key: "contact_name" },
          { key: "email", type: "email" },
          { key: "phone" },
          { key: "address" },
          { key: "city" },
          { key: "country" },
          { key: "tax_number" },
          { key: "payment_terms" },
          { key: "rating", type: "number", min: "0", max: "5", step: "0.01" },
          { key: "notes", type: "textarea" },
          { key: "is_active", type: "checkbox" },
        ]
      : kind === "parts"
        ? [
            { key: "part_number", required: true },
            { key: "name", required: true },
            {
              key: "category_id",
              required: true,
              type: "select",
              options: choices(options.data.categories),
            },
            { key: "manufacturer" },
            { key: "barcode" },
            { key: "unit", required: true },
            {
              key: "supplier_id",
              type: "select",
              options: choices(options.data.vendors),
            },
            {
              key: "unit_cost",
              required: true,
              type: "number",
              min: "0",
              step: "0.0001",
            },
            { key: "minimum_stock", type: "number", min: "0", step: "0.001" },
            { key: "description", type: "textarea" },
            { key: "is_active", type: "checkbox" },
          ]
        : kind === "technicians"
          ? [
              { key: "employee_number", required: true },
              { key: "full_name", required: true },
              { key: "specialization" },
              { key: "user_id", type: "number", min: "1" },
              { key: "email", type: "email" },
              { key: "phone" },
              {
                key: "hourly_rate",
                required: true,
                type: "number",
                min: "0",
                step: "0.01",
              },
              { key: "is_active", type: "checkbox" },
            ]
          : [
              { key: "name", required: true },
              { key: "description", type: "textarea" },
              { key: "is_active", type: "checkbox" },
            ];
  const columns =
    kind === "vendors"
      ? ["name", "vendor_type", "contact_name", "email", "phone", "rating"]
      : kind === "parts"
        ? [
            "part_number",
            "name",
            "category_name",
            "manufacturer",
            "supplier_name",
            "unit_cost",
            "total_stock",
          ]
        : kind === "technicians"
          ? ["employee_number", "full_name", "specialization", "hourly_rate"]
          : ["name", "description"];
  function edit(row: Row | null) {
    setEditing(row);
    setDialogError(null);
    setValues(
      Object.fromEntries(
        fields.map((f) => [
          f.key,
          f.type === "checkbox"
            ? row?.[f.key] !== false
            : String(
                row?.[f.key] ??
                  (
                    {
                      vendor_type: "Workshop",
                      unit: "piece",
                      unit_cost: "0",
                      minimum_stock: "0",
                      hourly_rate: "0",
                    } as Record<string, string>
                  )[f.key] ??
                  "",
              ),
        ]),
      ),
    );
    setOpen(true);
  }
  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setDialogError(null);
    try {
      const payload: Record<string, unknown> = { ...editing };
      fields.forEach((f) => {
        const v = values[f.key];
        payload[f.key] =
          v === ""
            ? null
            : (f.type === "select" && f.key.endsWith("_id")) ||
                f.key === "user_id"
              ? Number(v)
              : v;
      });
      if (kind === "vendors" || kind === "technicians")
        payload.status = values.is_active ? "Active" : "Inactive";
      if (editing) await apiPut(`/${kind}/${editing.id}`, payload);
      else await apiPost(`/${kind}`, payload);
      setOpen(false);
      await reload();
    } catch (e) {
      setDialogError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function archive(row: Row) {
    setBusy(true);
    setError(null);
    try {
      if (row.archived) await apiPost(`/${kind}/${row.id}/restore`, {});
      else if (kind === "part-categories")
        await apiPut(`/${kind}/${row.id}/archive`, {});
      else await apiDelete(`/${kind}/${row.id}`);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  const filtered =
    kind === "parts"
      ? data
      : data.filter((r) =>
          columns.some((c) =>
            String(r[c] ?? "")
              .toLowerCase()
              .includes(search.toLowerCase()),
          ),
        );
  if (!can(`${permission}.view`))
    return <p className="card">{text("noPermission")}</p>;
  return (
    <section>
      <MaintenancePageHeader
        title={text(kind)}
        description={text(`${kind}Description`)}
        actions={
          canWrite && (
            <button className="button" onClick={() => edit(null)}>
              {text("add")}
            </button>
          )
        }
      />
      <div className="card form spaced">
        <div className="formGrid">
          <label className="supplyField">
            {text("search")}
            <input
              className="input"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          {kind === "parts" && (
            <>
              <label className="supplyField">
                {text("category_id")}
                <select
                  className="select"
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                >
                  <option value="">{text("all")}</option>
                  {options.data.categories.map((x) => (
                    <option key={x.id} value={x.id}>
                      {x.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="supplyField">
                {text("supplier_id")}
                <select
                  className="select"
                  value={vendor}
                  onChange={(e) => setVendor(e.target.value)}
                >
                  <option value="">{text("all")}</option>
                  {options.data.vendors.map((x) => (
                    <option key={x.id} value={x.id}>
                      {x.name}
                    </option>
                  ))}
                </select>
              </label>
            </>
          )}
          <label>
            <input
              type="checkbox"
              checked={archived}
              onChange={(e) => setArchived(e.target.checked)}
            />{" "}
            {text("includeArchived")}
          </label>
        </div>
      </div>
      <SupplyNotice error={error ?? options.error} loading={loading} />
      <div className="card spaced">
        <MaintenanceTable>
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c}>{text(c)}</th>
              ))}
              <th>{text("status")}</th>
              {canWrite && <th>{text("actions")}</th>}
            </tr>
          </thead>
          <tbody>
            {filtered.map((row) => (
              <tr key={row.id}>
                {columns.map((c) => (
                  <td key={c}>
                    {c === "unit_cost" || c === "hourly_rate"
                      ? formatCurrency(Number(row[c]))
                      : c === "total_stock"
                        ? formatNumber(Number(row[c]))
                        : c === "vendor_type"
                          ? text(String(row[c]))
                          : String(row[c] ?? "—")}
                  </td>
                ))}
                <td>
                  <MaintenanceStatusBadge
                    status={
                      row.archived
                        ? "Archived"
                        : row.is_active === false
                          ? "Inactive"
                          : "Active"
                    }
                  />
                </td>
                {canWrite && (
                  <td>
                    <div className="actions">
                      {!row.archived && (
                        <button
                          className="secondaryButton smallButton"
                          disabled={busy}
                          onClick={() => edit(row)}
                        >
                          {text("edit")}
                        </button>
                      )}
                      <button
                        className="secondaryButton smallButton"
                        disabled={busy}
                        onClick={() => void archive(row)}
                      >
                        {text(row.archived ? "restore" : "archive")}
                      </button>
                    </div>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </MaintenanceTable>
        {!filtered.length && !loading && (
          <p className="muted">{text("empty")}</p>
        )}
      </div>
      <CreateEntityDialog
        open={open}
        title={text(editing ? "edit" : "add")}
        busy={busy}
        onClose={() => setOpen(false)}
      >
        <form className="form" onSubmit={save}>
          <SupplyNotice error={dialogError} />
          <Fields fields={fields} values={values} setValues={setValues} />
          <div className="actions">
            <button className="button" disabled={busy}>
              {text("save")}
            </button>
            <button
              className="secondaryButton"
              type="button"
              disabled={busy}
              onClick={() => setOpen(false)}
            >
              {text("cancel")}
            </button>
          </div>
        </form>
      </CreateEntityDialog>
    </section>
  );
}
