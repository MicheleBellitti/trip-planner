import type { AgentName } from "@/lib/schemas/generated/ui-event";

import { cx } from "./cx";
import { Icon, type IconName } from "./icon";

/** Each agent's line icon (Phosphor bold). The line colour comes from `data-agent` (globals.css
 * maps it to --line), so these two facts are the whole of an agent's visual identity. */
export const AGENT_ICONS: Record<AgentName, IconName> = {
  coordinator: "tree-structure",
  flights: "airplane-tilt",
  lodging: "bed",
  activities: "ticket",
  transport: "tram",
};

const ROUNDEL_SIZES = {
  sm: { box: "size-[26px]", icon: 15 },
  md: { box: "size-[30px]", icon: 17 },
  lg: { box: "size-[34px]", icon: 19 },
} as const;

/** The agent's roundel: a disc in the line colour with its icon, like a line badge on a transit
 * map. Decorative: the agent's name is always written next to it. */
export function AgentRoundel({
  agent,
  size = "md",
  className,
}: {
  agent: AgentName;
  size?: keyof typeof ROUNDEL_SIZES;
  className?: string;
}) {
  return (
    <span
      data-agent={agent}
      aria-hidden="true"
      className={cx(
        "inline-grid shrink-0 place-items-center rounded-full bg-line text-on-line",
        ROUNDEL_SIZES[size].box,
        className,
      )}
    >
      <Icon name={AGENT_ICONS[agent]} size={ROUNDEL_SIZES[size].icon} />
    </span>
  );
}
