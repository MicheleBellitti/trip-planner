"use client";

import { useEffect, useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";

interface InterruptControlProps {
  /** An interrupt is on its way (the agents close the step in progress). */
  interrupting: boolean;
  /** The plan is paused at its budget: nothing is running, so the question does not talk of steps. */
  paused?: boolean;
  /** Sends POST /plans/{id}/interrupt; resolves to an Italian error to show, or null. */
  onConfirm: () => Promise<string | null>;
}

/**
 * "Interrompi" with an inline confirmation: a small panel under the button says what stopping
 * means and asks to confirm. Esc, "Annulla" or a click outside close it and give the focus back
 * to the button. Not a modal: the page stays readable while deciding.
 */
export function InterruptControl({ interrupting, paused = false, onConfirm }: InterruptControlProps) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const id = useId();
  const triggerId = `${id}-trigger`;
  const cancelId = `${id}-cancel`;
  const panelId = `${id}-panel`;
  const questionId = `${id}-question`;
  // Button takes no ref (ComponentPropsWithoutRef): focus by id.
  const focus = (target: string) => document.getElementById(target)?.focus();

  const close = (focusTrigger: boolean) => {
    setOpen(false);
    setError(null);
    if (focusTrigger) focus(triggerId);
  };

  useEffect(() => {
    if (!open) return;
    focus(cancelId);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        setError(null);
        focus(triggerId);
      }
    };
    const onPointer = (event: PointerEvent) => {
      if (root.current && event.target instanceof Node && !root.current.contains(event.target)) {
        setOpen(false);
        setError(null);
      }
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open, cancelId, triggerId]);

  async function confirm() {
    setBusy(true);
    setError(null);
    const failure = await onConfirm();
    setBusy(false);
    if (failure) setError(failure);
    else setOpen(false);
  }

  if (interrupting) return <Button busy>Interrompo…</Button>;

  return (
    // On the phone the panel hangs from the whole control bar (the nearest positioned ancestor),
    // under the cost meter instead of over it; from 1080 px it hangs from the button.
    <div ref={root} className="lg:relative">
      <Button
        id={triggerId}
        icon="stop"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => (open ? close(false) : setOpen(true))}
      >
        Interrompi
      </Button>
      {open ? (
        <div
          id={panelId}
          role="group"
          aria-labelledby={questionId}
          className="absolute top-[calc(100%+0.5rem)] right-4 left-4 rounded-md border border-rule-strong bg-surface p-3.5 lg:-right-12 lg:left-auto lg:w-80 shadow-pop motion-safe:animate-toast-in motion-reduce:animate-fade-in"
        >
          <p id={questionId} className="text-small text-ink">
            {paused
              ? "Interrompere il piano? Il lavoro fatto finora resta qui, ma il piano non viene consegnato."
              : "Interrompere il piano? Gli agenti chiudono il passo in corso e il lavoro fatto finora resta qui, ma il piano non viene consegnato."}
          </p>
          {error ? (
            <Notice tone="error" role="alert" className="mt-3">
              {error}
            </Notice>
          ) : null}
          <div className="mt-3 flex flex-wrap justify-end gap-2">
            <Button id={cancelId} variant="quiet" onClick={() => close(true)} disabled={busy}>
              Annulla
            </Button>
            <Button variant="primary" busy={busy} onClick={() => void confirm()}>
              Interrompi il piano
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
