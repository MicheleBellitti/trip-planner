"use client";

import { useEffect, useRef } from "react";

/**
 * Inside the header's stations strip, which scrolls sideways when the three admin stations do not
 * fit (below about 360 px): brings the current station into view, with no animation and no
 * vertical scroll, so the "you are here" ring is never hidden past the edge. It runs on mount and
 * again whenever a station is added or removed: the admin's stations arrive only once GET /me has
 * answered (lib/me.ts), and "Valutazioni" then appears before "Inviti" and pushes it along.
 */
export function ScrollToCurrent() {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const strip = ref.current?.parentElement;
    if (!strip) return;
    const bring = () => strip.querySelector('[aria-current="page"]')?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
    bring();
    const observer = new MutationObserver(bring);
    observer.observe(strip, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);
  return <span ref={ref} hidden />;
}
