"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Whether the element has come within `margin` of the viewport; once it has, it stays true. A
 * browser with no IntersectionObserver (and the first server render) answers true after mount, so
 * a photo is never withheld for want of an observer. Attach `ref` to the element.
 */
export function useNearView<T extends Element>(margin = "300px") {
  const ref = useRef<T>(null);
  const [near, setNear] = useState(false);

  useEffect(() => {
    if (near) return;
    const element = ref.current;
    if (!element) return;
    if (typeof IntersectionObserver === "undefined") {
      // Not an external system to subscribe to: no observer means "load as soon as mounted".
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setNear(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setNear(true);
          observer.disconnect();
        }
      },
      { rootMargin: margin },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [near, margin]);

  return { ref, near };
}
