"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

export type ComboboxOption = {
  id: number;
  name: string;
};

type SearchableComboboxProps = {
  id: string;
  options: ComboboxOption[];
  value: number | null;
  selectedLabel?: string;
  onChange: (value: number | null) => void;
  placeholder: string;
  searchPlaceholder: string;
  emptyText: string;
  loadingText: string;
  loading?: boolean;
  disabled?: boolean;
  error?: string | null;
  required?: boolean;
};

export function SearchableCombobox({
  id,
  options,
  value,
  selectedLabel,
  onChange,
  placeholder,
  searchPlaceholder,
  emptyText,
  loadingText,
  loading = false,
  disabled = false,
  error,
  required = false
}: SearchableComboboxProps) {
  const { t } = useTranslation("modules");
  const generatedId = useId();
  const listboxId = `${generatedId}-listbox`;
  const statusId = `${generatedId}-status`;
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(-1);
  const selected = options.find((option) => option.id === value);
  const filtered = useMemo(() => {
    const search = query.trim().toLocaleLowerCase();
    if (!search) return options;
    return options.filter((option) => option.name.toLocaleLowerCase().includes(search));
  }, [options, query]);

  useEffect(() => {
    setActiveIndex(filtered.length > 0 ? 0 : -1);
  }, [filtered]);

  function choose(option: ComboboxOption) {
    onChange(option.id);
    setQuery("");
    setOpen(false);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActiveIndex((index) => filtered.length === 0 ? -1 : Math.min(index + 1, filtered.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      setActiveIndex((index) => filtered.length === 0 ? -1 : Math.max(index - 1, 0));
    } else if (event.key === "Enter" && open && activeIndex >= 0) {
      event.preventDefault();
      choose(filtered[activeIndex]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      setQuery("");
      setOpen(false);
    } else if (event.key === "Tab") {
      setQuery("");
      setOpen(false);
    }
  }

  const unavailableSelection = value !== null && !loading && !error && !selected;
  const displayValue = open ? query : (selected?.name ?? selectedLabel ?? "");
  const activeOptionId = open && activeIndex >= 0 ? `${listboxId}-option-${filtered[activeIndex].id}` : undefined;

  return (
    <div className="combobox">
      <div className="comboboxInputWrap">
        <input
          id={id}
          className="input comboboxInput"
          role="combobox"
          aria-autocomplete="list"
          aria-controls={listboxId}
          aria-expanded={open}
          aria-activedescendant={activeOptionId}
          aria-describedby={statusId}
          aria-invalid={Boolean(error)}
          aria-required={required}
          autoComplete="off"
          disabled={disabled}
          required={required}
          value={displayValue}
          placeholder={open ? searchPlaceholder : placeholder}
          onFocus={() => {
            setQuery("");
            setOpen(true);
          }}
          onClick={() => {
            setQuery("");
            setOpen(true);
          }}
          onBlur={() => window.setTimeout(() => {
            setQuery("");
            setOpen(false);
          }, 100)}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
            if (value !== null) onChange(null);
          }}
          onKeyDown={handleKeyDown}
        />
        <span className="comboboxChevron" aria-hidden="true">⌄</span>
      </div>
      {open && !disabled && (
        <div id={listboxId} className="comboboxList" role="listbox">
          {loading ? (
            <div className="comboboxMessage">{loadingText}</div>
          ) : error ? (
            <div className="comboboxMessage comboboxError">{error}</div>
          ) : filtered.length === 0 ? (
            <div className="comboboxMessage">{emptyText}</div>
          ) : filtered.map((option, index) => (
            <button
              id={`${listboxId}-option-${option.id}`}
              key={option.id}
              type="button"
              role="option"
              aria-selected={option.id === value}
              className={`comboboxOption${index === activeIndex ? " active" : ""}`}
              onMouseDown={(event) => event.preventDefault()}
              onMouseEnter={() => setActiveIndex(index)}
              onClick={() => choose(option)}
            >
              {option.name}
            </button>
          ))}
        </div>
      )}
      <div id={statusId} className={`comboboxStatus${error ? " comboboxError" : ""}`} aria-live="polite">
        {loading ? loadingText : error || (unavailableSelection ? t("shared.historicalSelectionUnavailable") : "")}
      </div>
    </div>
  );
}
