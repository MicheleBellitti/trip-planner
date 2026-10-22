import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useClockSkew } from "./hooks";

const SERVER = Date.parse("2026-10-12T10:00:00Z");
const at = (ms: number) => new Date(ms).toISOString();

interface Props {
  clock: number | null;
  serverNow?: string | null;
  samples?: (string | null | undefined)[];
}

function skewOf(initial: Props) {
  return renderHook(({ clock, serverNow, samples }: Props) => useClockSkew(clock, serverNow, samples ?? []), {
    initialProps: initial,
  });
}

describe("useClockSkew", () => {
  it("is 0 before any sample, and samples nothing on a null clock", () => {
    const hook = skewOf({ clock: null, serverNow: at(SERVER), samples: [at(SERVER)] });
    expect(hook.result.current).toBe(0);
    hook.rerender({ clock: SERVER + 5_000 });
    expect(hook.result.current).toBe(0);
  });

  it("without the server's now (an older backend), keeps the smallest gap to the timestamps", () => {
    const hook = skewOf({ clock: SERVER + 90_000, samples: [at(SERVER), at(SERVER + 30_000)] });
    expect(hook.result.current).toBe(60_000);
    // A later clock over the same timestamps never raises it; a newer timestamp lowers it.
    hook.rerender({ clock: SERVER + 200_000, samples: [at(SERVER + 30_000)] });
    expect(hook.result.current).toBe(60_000);
    hook.rerender({ clock: SERVER + 200_000, samples: [at(SERVER + 195_000)] });
    expect(hook.result.current).toBe(5_000);
  });

  it("takes each new server now as the skew, above the timestamps' and above what came before", () => {
    const hook = skewOf({ clock: SERVER + 300_000, serverNow: at(SERVER + 120_000), samples: [at(SERVER)] });
    // Not the 5 minutes to the timestamp: the 3 minutes to the server's now.
    expect(hook.result.current).toBe(180_000);
    // The same value later is no new sample.
    hook.rerender({ clock: SERVER + 360_000, serverNow: at(SERVER + 120_000), samples: [at(SERVER)] });
    expect(hook.result.current).toBe(180_000);
    // A device clock stepped 2 minutes forward: the next server now replaces the skew, upward.
    hook.rerender({ clock: SERVER + 500_000, serverNow: at(SERVER + 200_000), samples: [at(SERVER)] });
    expect(hook.result.current).toBe(300_000);
  });

  it("lets a newer timestamp lower the skew until the next server now", () => {
    const hook = skewOf({ clock: SERVER + 10_000, serverNow: at(SERVER) });
    expect(hook.result.current).toBe(10_000);
    hook.rerender({ clock: SERVER + 12_000, serverNow: at(SERVER), samples: [at(SERVER + 4_000)] });
    expect(hook.result.current).toBe(8_000);
    hook.rerender({ clock: SERVER + 20_000, serverNow: at(SERVER + 11_000), samples: [at(SERVER + 4_000)] });
    expect(hook.result.current).toBe(9_000);
  });

  it("ignores what does not parse, without rendering again and again", () => {
    let renders = 0;
    const hook = renderHook(
      ({ clock, serverNow }: { clock: number; serverNow: string }) => {
        renders += 1;
        return useClockSkew(clock, serverNow, ["not a time", undefined, null, ""]);
      },
      { initialProps: { clock: SERVER, serverNow: "not a time" } },
    );
    expect(hook.result.current).toBe(0);
    hook.rerender({ clock: Number.NaN, serverNow: at(SERVER) });
    expect(hook.result.current).toBe(0);
    expect(renders).toBe(2);
  });
});
