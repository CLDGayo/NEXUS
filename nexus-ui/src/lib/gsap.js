import { gsap } from 'gsap';

export { gsap };

// Shared motion tokens — keep every animation across the app consistent.
export const EASE = {
  pressDown: 'power2.out',
  pressUp: 'elastic.out(1, 0.4)',
  pageIn: 'power3.out',
  childIn: 'power2.out',
};

export const DUR = {
  pressDown: 0.12,
  pressUp: 0.45,
  pageIn: 0.35,
  childIn: 0.4,
};

// Honor the user's motion preference. Checked at run time (not module load)
// because the setting can change during a session.
export function prefersReducedMotion() {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}
