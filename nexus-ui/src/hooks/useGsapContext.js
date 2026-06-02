import { useEffect } from 'react';
import { gsap } from '../lib/gsap';

/**
 * StrictMode-safe GSAP scoping.
 *
 * Wraps gsap.context() so every tween/timeline/listener created inside `setup`
 * is reverted on cleanup. In React 18 StrictMode the effect runs, cleans up,
 * then runs again in dev — ctx.revert() restores pre-animation inline styles
 * and kills tweens, so the second run starts clean (no doubled timelines, no
 * element stuck at opacity:0). `setup` may return its own cleanup fn (e.g.
 * removeEventListener); gsap.context invokes it on revert.
 */
export function useGsapContext(scopeRef, setup, deps = []) {
  useEffect(() => {
    if (!scopeRef.current) return undefined;
    const ctx = gsap.context(setup, scopeRef);
    return () => ctx.revert();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}
