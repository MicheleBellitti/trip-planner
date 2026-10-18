"use client";

import { useEffect, useRef } from "react";

/**
 * Inside the header's stations strip, which scrolls sideways when the three admin stations do not
 * fit (below about 360 px): brings the current station into view, with no animation, so the
 * "you are here" ring is never hidden past the edge. It runs on mount and again whenever a station
 * is added or removed: the admin's stations arrive only once GET /me has answered (lib/me.ts), and
 * "Collaudi" then appears before "Inviti" and pushes it along. It moves the strip's own
 * `scrollLeft` and nothing else: `scrollIntoView` would also scroll the window (the header is not
 * sticky), and the page would jump to the top when the admin stations arrive.
 */
export function ScrollToCurrent() {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const strip = ref.current?.parentElement;
    if (!strip) return;
    const bring = () => {
      const current = strip.querySelector('[aria-current="page"]');
      if (!current) return;
      const view = strip.getBoundingClientRect();
      const box = current.getBoundingClientRect();
      let shift = 0;
      if (box.left < view.left) shift = box.left - view.left;
      else if (box.right > view.right) shift = Math.min(box.right - view.right, box.left - view.left);
      if (shift !== 0) strip.scrollLeft += shift;
    };
    bring();
    const observer = new MutationObserver(bring);
    observer.observe(strip, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);
  return <span ref={ref} hidden />;
}
