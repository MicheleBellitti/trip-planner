"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";

import { cx } from "./cx";
import { IconButton } from "./icon-button";

interface SheetProps {
  open: boolean;
  /** Called with false when the sheet closes by itself: Esc, the close button, a tap on the
   * scrim. Set `open` from it. */
  onOpenChange: (open: boolean) => void;
  /** The heading, also the dialog's accessible name. Sentence case, no trailing period. */
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  /** Actions, right-aligned on desktop and full width on the phone: the safe one first in the
   * DOM ("Continua"), the committing one last ("Interrompi il piano"). */
  footer?: ReactNode;
  className?: string;
}

/**
 * A modal sheet on the native <dialog> (focus moves in and back, Esc closes, the page behind is
 * inert and does not scroll). On the phone it rises from the bottom edge, full width, with the
 * safe-area inset; from 768 px it is a centred 28 rem panel. Motion: 240 ms expo out, rising from
 * below on the phone and 8 px on desktop, with the scrim fading; reduced motion keeps only the
 * fades. For confirmations and short forms only: anything longer is a page.
 */
export function Sheet({ open, onOpenChange, title, description, children, footer, className }: SheetProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      data-modal=""
      aria-labelledby={titleId}
      aria-describedby={description ? descriptionId : undefined}
      onClose={() => onOpenChange(false)}
      onClick={(event) => {
        // A click whose target is the <dialog> itself landed on the scrim (::backdrop): the
        // panel's content sits in the inner <div>.
        if (event.target === event.currentTarget) event.currentTarget.close();
      }}
      className={cx(
        // Phone: docked to the bottom edge, full width.
        "m-0 mt-auto h-fit max-h-[85dvh] w-full max-w-full overflow-visible border-0 bg-transparent p-0 text-ink",
        // Desktop: a centred panel.
        "md:m-auto md:max-w-[28rem]",
        // Open and close: opacity everywhere, movement only without reduced motion.
        "opacity-0 open:opacity-100 starting:open:opacity-0",
        "motion-safe:translate-y-full motion-safe:open:translate-y-0 motion-safe:starting:open:translate-y-full",
        "md:motion-safe:translate-y-2 md:motion-safe:open:translate-y-0 md:motion-safe:starting:open:translate-y-2",
        "transition-[opacity,translate,display,overlay] transition-discrete duration-(--duration-expand) ease-expo",
        "motion-reduce:duration-(--duration-reduced)",
        "backdrop:bg-scrim backdrop:opacity-0 open:backdrop:opacity-100 starting:open:backdrop:opacity-0",
        "backdrop:transition-[opacity,display,overlay] backdrop:transition-discrete backdrop:duration-(--duration-expand)",
      )}
    >
      <div
        className={cx(
          "max-h-[85dvh] overflow-y-auto rounded-t-md bg-surface px-4 pt-4 pb-[max(1rem,env(safe-area-inset-bottom))] shadow-pop",
          "md:rounded-md md:p-5",
          className,
        )}
      >
        <div className="flex items-start justify-between gap-3">
          <h2 id={titleId} className="pt-1.5 font-cond text-heading font-semibold">
            {title}
          </h2>
          <IconButton icon="x" label="Chiudi" size="sm" onClick={() => ref.current?.close()} />
        </div>
        {description ? (
          <div id={descriptionId} className="mt-2 text-small text-ink-2">
            {description}
          </div>
        ) : null}
        {children ? <div className="mt-4">{children}</div> : null}
        {footer ? (
          <div className="mt-5 grid gap-2 sm:flex sm:flex-wrap sm:justify-end [&>*]:w-full sm:[&>*]:w-auto">
            {footer}
          </div>
        ) : null}
      </div>
    </dialog>
  );
}
