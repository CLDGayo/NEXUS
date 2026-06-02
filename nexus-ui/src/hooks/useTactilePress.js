import { useRef } from 'react';
import { gsap, EASE, DUR, prefersReducedMotion } from '../lib/gsap';
import { useGsapContext } from './useGsapContext';

/**
 * Tactile press feedback. Attach the returned ref to any pressable element.
 * pointerdown → compress (scale .95); pointerup/leave → elastic spring back.
 * No-op under prefers-reduced-motion. Listeners are detached via the context's
 * returned cleanup, so it is StrictMode-safe.
 */
export function useTactilePress() {
  const ref = useRef(null);

  useGsapContext(ref, () => {
    const el = ref.current;
    if (!el || prefersReducedMotion()) return undefined;

    const down = () =>
      gsap.to(el, { scale: 0.95, duration: DUR.pressDown, ease: EASE.pressDown });
    const up = () =>
      gsap.to(el, { scale: 1, duration: DUR.pressUp, ease: EASE.pressUp });

    el.addEventListener('pointerdown', down);
    el.addEventListener('pointerup', up);
    el.addEventListener('pointerleave', up);

    return () => {
      el.removeEventListener('pointerdown', down);
      el.removeEventListener('pointerup', up);
      el.removeEventListener('pointerleave', up);
    };
  }, []);

  return ref;
}
