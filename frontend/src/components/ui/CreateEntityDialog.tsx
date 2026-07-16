"use client";

import { useEffect, useId, useRef } from "react";

type CreateEntityDialogProps = {
  open: boolean;
  title: string;
  description?: string;
  busy?: boolean;
  onClose: () => void;
  children: React.ReactNode;
};

const FOCUSABLE_SELECTOR = [
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "button:not([disabled])",
  "a[href]",
  "[tabindex]:not([tabindex='-1'])"
].join(",");

export function CreateEntityDialog({ open, title, description, busy = false, onClose, children }: CreateEntityDialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const busyRef = useRef(busy);

  onCloseRef.current = onClose;
  busyRef.current = busy;

  useEffect(() => {
    if (!open) return;

    previouslyFocused.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const focusTimer = window.setTimeout(() => {
      const firstControl = dialogRef.current?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
      (firstControl ?? dialogRef.current)?.focus();
    }, 0);

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        if (!busyRef.current) {
          event.preventDefault();
          onCloseRef.current();
        }
        return;
      }

      if (event.key !== "Tab" || !dialogRef.current) return;
      const controls = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
        .filter((element) => element.offsetParent !== null);
      if (controls.length === 0) {
        event.preventDefault();
        dialogRef.current.focus();
        return;
      }

      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
      previouslyFocused.current?.focus();
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className="dialogOverlay">
      <div
        ref={dialogRef}
        className="dialogPanel"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
      >
        <div className="dialogHeader">
          <div>
            <h2 id={titleId}>{title}</h2>
            {description && <p id={descriptionId} className="muted">{description}</p>}
          </div>
          <button
            className="dialogCloseButton"
            type="button"
            aria-label={`Close ${title}`}
            onClick={onClose}
            disabled={busy}
          >
            <span aria-hidden="true">×</span>
          </button>
        </div>
        <div className="dialogBody">{children}</div>
      </div>
    </div>
  );
}
