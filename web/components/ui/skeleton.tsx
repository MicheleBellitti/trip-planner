import { cx } from "./cx";

const SHAPES = {
  line: "h-[0.8em] rounded-xs",
  block: "rounded-sm",
  round: "rounded-full",
} as const;

/**
 * A placeholder in the shape of what is coming (a lane card, a station row, a roundel), never a
 * generic spinner. Size it with the same classes as the final element (h-*, w-*, size-*).
 * The rule-coloured fill breathes slowly (1.6 s) while loading; with reduced motion it holds
 * still. Decorative: put aria-busy on the region that is loading and a VisuallyHidden
 * "Caricamento…" inside it.
 */
export function Skeleton({ shape = "line", className }: { shape?: keyof typeof SHAPES; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cx("block bg-rule motion-safe:animate-breathe", SHAPES[shape], className)}
    />
  );
}
