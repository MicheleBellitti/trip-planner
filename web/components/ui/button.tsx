import Link from "next/link";
import type { ComponentPropsWithoutRef, ReactNode } from "react";

import { cx } from "./cx";
import { Icon, type IconName } from "./icon";
import { VisuallyHidden } from "./visually-hidden";

/**
 * Buttons are ink, never amber (DESIGN.md, "The Amber Is Spoken For Rule"): amber belongs to
 * bookings due soon and nothing else, the import button included. There is no prop that can
 * colour a button; `className` is for layout only (width, margins, grid placement).
 */
export type ButtonVariant = "primary" | "secondary" | "quiet";
export type ButtonSize = "md" | "sm";

const BASE =
  "inline-flex items-center justify-center gap-2 rounded-full border-[1.5px] font-semibold whitespace-nowrap " +
  "select-none no-underline transition-[background-color,border-color,color,scale] duration-(--duration-hover) ease-out " +
  "active:scale-[0.98] active:duration-(--duration-press) motion-reduce:active:scale-100 " +
  "disabled:cursor-not-allowed disabled:opacity-55 aria-disabled:cursor-not-allowed aria-disabled:opacity-55";

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "border-action bg-action text-on-action " +
    "not-disabled:hover:border-[color-mix(in_srgb,var(--action)_86%,var(--ground))] " +
    "not-disabled:hover:bg-[color-mix(in_srgb,var(--action)_86%,var(--ground))]",
  secondary: "border-ink bg-transparent text-ink not-disabled:hover:bg-notice-wash",
  quiet: "border-transparent bg-transparent text-ink underline-offset-[0.2em] not-disabled:hover:bg-notice-wash",
};

const SIZES: Record<ButtonSize, { box: string; icon: number }> = {
  md: { box: "min-h-10 px-4 text-small", icon: 16 },
  sm: { box: "min-h-8 px-3 text-meta", icon: 14 },
};

/** Class string of a button, for the rare element that must look like one but cannot be a
 * <Button> or <LinkButton> (a <summary>, a form's submit inside a third-party wrapper). */
export function buttonClasses(variant: ButtonVariant = "secondary", size: ButtonSize = "md"): string {
  return cx(BASE, VARIANTS[variant], SIZES[size].box);
}

function BusyGlyph({ size }: { size: number }) {
  // The reconnect arrows, turning: the same "working on it" sign as the stream line. Reduced
  // motion keeps it still; the label and aria-busy carry the state.
  return <Icon name="arrows-clockwise" size={size} className="motion-safe:animate-turn" />;
}

interface ButtonProps extends ComponentPropsWithoutRef<"button"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** A Phosphor icon before the label. */
  icon?: IconName;
  /** The action is under way: disabled, aria-busy, and the icon turns. Change the label too when
   * the wait can be long ("Interrompo il piano…"). */
  busy?: boolean;
  children: ReactNode;
}

/** A button: an action verb in sentence case ("Pianifica il viaggio", "Interrompi"). */
export function Button({
  variant = "secondary",
  size = "md",
  icon,
  busy = false,
  disabled,
  type = "button",
  className,
  children,
  ...props
}: ButtonProps) {
  const iconSize = SIZES[size].icon;
  return (
    <button
      type={type}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={cx(buttonClasses(variant, size), className)}
      {...props}
    >
      {busy ? <BusyGlyph size={iconSize} /> : icon ? <Icon name={icon} size={iconSize} /> : null}
      {children}
    </button>
  );
}

interface LinkButtonProps extends Omit<ComponentPropsWithoutRef<"a">, "href" | "target" | "rel"> {
  href: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: IconName;
  /** Opens another site in a new tab with rel="noopener noreferrer" ("Prenota su <sito>", "Apri
   * in TripTracker") and says so to screen readers. Internal links use next/link. */
  external?: boolean;
  children: ReactNode;
}

/** A link styled as a button: navigation, never an action. */
export function LinkButton({
  href,
  variant = "secondary",
  size = "md",
  icon,
  external = false,
  className,
  children,
  ...props
}: LinkButtonProps) {
  const iconSize = SIZES[size].icon;
  const classes = cx(buttonClasses(variant, size), className);
  const leading = icon ? <Icon name={icon} size={iconSize} /> : null;
  if (external) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className={classes} {...props}>
        {leading}
        {children}
        <Icon name="arrow-square-out" size={iconSize} />
        <VisuallyHidden> (si apre in una nuova scheda)</VisuallyHidden>
      </a>
    );
  }
  return (
    <Link href={href} className={classes} {...props}>
      {leading}
      {children}
    </Link>
  );
}
