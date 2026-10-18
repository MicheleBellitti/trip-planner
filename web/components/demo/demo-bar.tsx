"use client";

import { Button } from "@/components/ui/button";

/**
 * The demo's bar (spec, "Demo"), in place of "Interrompi": what this run is, then "Ricomincia",
 * "2×" and "Salta al piano" (the last two only while the run plays). Its own row in the live
 * header's state group, so it fits a phone beside nothing else.
 */
export function DemoBar({
  speed,
  onSpeed,
  onRestart,
  onSkip,
  done,
}: {
  speed: number;
  onSpeed: (speed: number) => void;
  onRestart: () => void;
  onSkip: () => void;
  done: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-rule pt-2.5 lg:border-0 lg:pt-0">
      <p className="text-meta text-ink-2">Corsa dimostrativa: dati di esempio, gratis per te</p>
      <div className="flex items-center gap-2">
        <Button size="sm" variant="quiet" icon="arrows-clockwise" onClick={onRestart} className="pointer-coarse:min-h-11">
          Ricomincia
        </Button>
        {done ? null : (
          <>
            <Button
              size="sm"
              variant="secondary"
              aria-pressed={speed === 2}
              onClick={() => onSpeed(speed === 2 ? 1 : 2)}
              className="pointer-coarse:min-h-11 pointer-coarse:min-w-11 aria-pressed:inset-ring-[1.5px] aria-pressed:inset-ring-ink"
            >
              2×
            </Button>
            <Button size="sm" variant="secondary" onClick={onSkip} className="pointer-coarse:min-h-11">
              Salta al piano
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
