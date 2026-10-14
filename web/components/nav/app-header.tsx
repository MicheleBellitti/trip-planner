import { ThemeToggle } from "@/components/ui/theme-toggle";

import { AppHeaderBar, type AppSection } from "./app-header-bar";

export type { AppSection };

/** The header of every signed-in page (DESIGN.md, Navigation): the bar with the theme toggle at
 * its end. The live screen uses the compact AppHeaderBar instead, whose control bar has the toggle. */
export function AppHeader({ current }: { current?: AppSection }) {
  return <AppHeaderBar current={current} trailing={<ThemeToggle variant="bare" className="pointer-coarse:size-11" />} />;
}
