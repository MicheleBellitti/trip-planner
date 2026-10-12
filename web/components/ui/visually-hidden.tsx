import type { ComponentPropsWithoutRef, ElementType } from "react";

type VisuallyHiddenProps<T extends ElementType> = {
  /** The element to render, a <span> by default. */
  as?: T;
} & ComponentPropsWithoutRef<T>;

/**
 * Text for screen readers only: still in the accessibility tree, out of sight (Tailwind's
 * sr-only). Use it to finish a sentence the layout abbreviates ("(si apre in una nuova scheda)")
 * or to name a section the eye reads from its position. Never to hide something sighted users
 * need.
 */
export function VisuallyHidden<T extends ElementType = "span">({ as, className, ...props }: VisuallyHiddenProps<T>) {
  const Component: ElementType = as ?? "span";
  return <Component className={className ? `sr-only ${className}` : "sr-only"} {...props} />;
}
