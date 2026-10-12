import type { SVGProps } from "react";

import { cx } from "./cx";
import type { IconName } from "./icons";

export type { IconName };

/** Symbol ids in the sprite (./icon-sprite.tsx): `icon-<phosphor name>`. */
export const ICON_SYMBOL_PREFIX = "icon-";

interface IconProps extends Omit<SVGProps<SVGSVGElement>, "children"> {
  name: IconName;
  /** An accessible name, only when the icon is the sole carrier of meaning. Most icons sit next
   * to a word and stay decorative (aria-hidden). */
  label?: string;
  /** Side in px, from the icon scale (DESIGN.md, Iconography): 12 to 20. Without it the icon is
   * 1em and follows the text around it. */
  size?: number;
}

/**
 * A Phosphor icon (bold) from the sprite the root layout renders: 1em square, filled with
 * currentColor, sized by font-size or a size-* class. Works in Server and Client Components and
 * costs no path data in JavaScript (the names are a type only).
 */
export function Icon({ name, label, size, className, style, ...props }: IconProps) {
  return (
    <svg
      aria-hidden={label ? undefined : true}
      role={label ? "img" : undefined}
      aria-label={label}
      focusable="false"
      className={cx("size-[1em] shrink-0 fill-current", className)}
      style={size === undefined ? style : { width: size, height: size, ...style }}
      {...props}
    >
      <use href={`#${ICON_SYMBOL_PREFIX}${name}`} />
    </svg>
  );
}
