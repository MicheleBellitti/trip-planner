import { cx } from "@/components/ui/cx";
import { VisuallyHidden } from "@/components/ui/visually-hidden";

import type { RunDelta } from "./eval-model";

const DELTA_TONES: Record<RunDelta["trend"], string> = {
  better: "text-success",
  worse: "text-error",
  same: "text-ink-2",
};

/** How a figure moved since the run before, under the figure in its <dl>: the sign carries the
 * direction, the colour only whether that is good news (The Green Means Passed Rule). */
export function DeltaNote({ delta }: { delta: RunDelta | null }) {
  if (!delta) return null;
  return (
    <dd className={cx("mt-0.5 text-meta font-medium", DELTA_TONES[delta.trend])}>
      {delta.text}
      <VisuallyHidden> rispetto al precedente</VisuallyHidden>
    </dd>
  );
}
