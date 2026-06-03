/**
 * useGraphDimensions.js — ResizeObserver hook that feeds explicit px
 * dimensions to react-force-graph-2d (which requires explicit width/height;
 * CSS percent dimensions are not supported on the canvas).
 *
 * Returns { width: 0, height: 0 } until the first measurement fires so the
 * caller can guard against mounting <ForceGraph2D> with a 0-dimension canvas.
 *
 * Re-measures on any container resize — including sidebar collapse, which
 * reflows the flex main and changes the container's pixel width. No extra
 * wiring to SidebarProvider is needed; ResizeObserver picks it up naturally.
 *
 * StrictMode-safe: the observer is disconnected in the effect cleanup, so the
 * double-invoke in development does not leave a leaked observer.
 */

import { useState, useEffect } from 'react';

export function useGraphDimensions(containerRef) {
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    // Measure immediately on mount (before first resize event)
    const measure = () => {
      setDimensions({
        width:  el.offsetWidth,
        height: el.offsetHeight,
      });
    };

    measure();

    const observer = new ResizeObserver(measure);
    observer.observe(el);

    // StrictMode-safe cleanup
    return () => {
      observer.disconnect();
    };
  }, [containerRef]);

  return dimensions;
}
