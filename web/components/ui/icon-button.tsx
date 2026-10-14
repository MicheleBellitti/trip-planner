import type { ComponentPropsWithoutRef } from "react";

import { cx } from "./cx";
import { Icon, type IconName } from "./icon";

const SIZES = {
  md: { box: "size-10", icon: 18 },
  sm: { box: "size-8", icon: 15 },
} as const;

/** Class string of an icon button, for a link that must look like one (the header's "Nuovo piano"
 * on the phone). */
export function iconButtonClasses(size: keyof typeof SIZES = "md", variant: "outline" | "bare" = "outline"): string {
  return cx(
    "inline-grid shrink-0 place-items-center rounded-full border-[1.5px] bg-transparent text-ink",
    variant === "outline" ? "border-rule-strong" : "border-transparent",
    "transition-[background-color,scale] duration-(--duration-hover) ease-out not-disabled:hover:bg-notice-wash",
    "aria-[current=page]:bg-notice-wash",
    "active:scale-[0.96] active:duration-(--duration-press) motion-reduce:active:scale-100",
    "disabled:cursor-not-allowed disabled:opacity-55",
    SIZES[size].box,
  );
}

interface IconButtonProps extends Omit<ComponentPropsWithoutRef<"button">, "children" | "aria-label"> {
  icon: IconName;
  /** The accessible name, an action verb in Italian ("Chiudi", "Passa al tema scuro"). Required:
   * an icon alone never names an action. */
  label: string;
  size?: keyof typeof SIZES;
  /** `outline`: a 3:1 rule-strong ring, for standalone controls (theme, close a sheet).
   * `bare`: no ring, inside a framed element that already has an edge (a toast). */
  variant?: "outline" | "bare";
}

/** A round icon-only button with a 3:1 control border (rule-strong). Same states as Button:
 * hover wash, press scale (none with reduced motion), focus ring, disabled at 55 %. */
export function IconButton({
  icon,
  label,
  size = "md",
  variant = "outline",
  type = "button",
  className,
  ...props
}: IconButtonProps) {
  return (
    <button
      type={type}
      aria-label={label}
      title={label}
      className={cx(iconButtonClasses(size, variant), className)}
      {...props}
    >
      <Icon name={icon} size={SIZES[size].icon} />
    </button>
  );
}
