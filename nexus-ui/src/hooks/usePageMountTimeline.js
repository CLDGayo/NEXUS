import { useRef } from 'react';
import { gsap, EASE, DUR, prefersReducedMotion } from '../lib/gsap';
import { useGsapContext } from './useGsapContext';

/**
 * Page-enter choreography. Attach the returned ref to a page's root container;
 * mark staggered children with `data-animate` (or pass a custom selector).
 * The container fades/scales in and children cascade up in a stagger. Under
 * prefers-reduced-motion, elements are set to their final state instantly.
 */
export function usePageMountTimeline({ childSelector = '[data-animate]' } = {}) {
  const ref = useRef(null);

  useGsapContext(ref, () => {
    const root = ref.current;
    if (!root) return;
    const children = root.querySelectorAll(childSelector);

    if (prefersReducedMotion()) {
      gsap.set(root, { opacity: 1, scale: 1 });
      if (children.length) gsap.set(children, { opacity: 1, y: 0 });
      return;
    }

    const tl = gsap.timeline();
    tl.from(root, { opacity: 0, scale: 0.98, duration: DUR.pageIn, ease: EASE.pageIn });
    if (children.length) {
      tl.from(
        children,
        { y: 30, opacity: 0, stagger: 0.04, duration: DUR.childIn, ease: EASE.childIn },
        '-=0.15',
      );
    }
  }, []);

  return ref;
}
