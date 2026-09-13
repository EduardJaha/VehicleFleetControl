"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiGet } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export type Option = { id: number; name: string; unit_cost?: string | number };
export type Options = {
  parts: Option[];
  categories: Option[];
  locations: Option[];
  vendors: Option[];
  technicians: Option[];
};
export const emptyOptions: Options = {
  parts: [],
  categories: [],
  locations: [],
  vendors: [],
  technicians: [],
};
export type Row = { id: number; archived?: boolean; [key: string]: unknown };
export type Field = {
  key: string;
  label?: string;
  type?:
    | "text"
    | "number"
    | "email"
    | "date"
    | "textarea"
    | "select"
    | "checkbox";
  required?: boolean;
  options?: Array<{ value: string; label: string }>;
  min?: string;
  max?: string;
  step?: string;
};
export type Values = Record<string, string | boolean>;
export const choices = (rows: Option[]) =>
  rows.map((r) => ({ value: String(r.id), label: r.name }));

export function useSupplyData<T>(path: string, initial: T, enabled = true) {
  const [data, setData] = useState<T>(initial);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const { user } = useAuth();
  const generation = useRef(0);
  const initialValue = useRef(initial);
  const reload = useCallback(async () => {
    const request = ++generation.current;
    if (!enabled || !user) {
      setLoading(false);
      return;
    }
    setError(null);
    try {
      const next = await apiGet<T>(path);
      if (request === generation.current) setData(next);
    } catch (e) {
      if (request === generation.current)
        setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }, [path, enabled, user]);
  useEffect(() => {
    setData(initialValue.current);
    setLoading(true);
    void reload();
    return () => {
      generation.current += 1;
    };
  }, [reload]);
  return { data, error, setError, loading, reload };
}

export function Fields({
  fields,
  values,
  setValues,
}: {
  fields: Field[];
  values: Values;
  setValues: (values: Values) => void;
}) {
  const { t } = useTranslation("modules");
  return (
    <div className="formGrid">
      {fields.map((field) => {
        const label = t(`supply.${field.label ?? field.key}`);
        const update = (value: string | boolean) =>
          setValues({ ...values, [field.key]: value });
        return (
          <label className="supplyField" key={field.key}>
            <span>
              {label}
              {field.required ? " *" : ""}
            </span>
            {field.type === "select" ? (
              <select
                className="select"
                required={field.required}
                value={String(values[field.key] ?? "")}
                onChange={(e) => update(e.target.value)}
              >
                <option value="">{t("supply.select")}</option>
                {field.options?.map((o) => (
                  <option value={o.value} key={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            ) : field.type === "checkbox" ? (
              <input
                type="checkbox"
                checked={Boolean(values[field.key])}
                onChange={(e) => update(e.target.checked)}
              />
            ) : field.type === "textarea" ? (
              <textarea
                className="input"
                value={String(values[field.key] ?? "")}
                onChange={(e) => update(e.target.value)}
              />
            ) : (
              <input
                className="input"
                type={field.type ?? "text"}
                required={field.required}
                min={field.min}
                max={field.max}
                step={field.step}
                value={String(values[field.key] ?? "")}
                onChange={(e) => update(e.target.value)}
              />
            )}
          </label>
        );
      })}
    </div>
  );
}

export function SupplyNotice({
  error,
  loading,
}: {
  error?: string | null;
  loading?: boolean;
}) {
  const { t } = useTranslation("modules");
  return (
    <>
      {error && (
        <div role="alert" className="error spaced">
          {error}
        </div>
      )}
      {loading && (
        <p role="status" className="muted">
          {t("supply.loading")}
        </p>
      )}
    </>
  );
}
