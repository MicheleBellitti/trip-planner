/** Joins class names, skipping falsy ones. Later classes do not override earlier ones by
 * themselves (no tailwind-merge, to keep the bundle small): a component's `className` prop is
 * for layout (margins, width, grid placement), never for its colours or shape. */
export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}
