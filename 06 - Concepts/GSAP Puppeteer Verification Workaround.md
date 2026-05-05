---
title: GSAP Puppeteer Verification Workaround
tags: [concept, gsap, puppeteer, testing, animation]
created: 2026-05-05
---

# GSAP Puppeteer Verification Workaround

When using GSAP ScrollTrigger, elements start at `opacity: 0` via inline style. Puppeteer's synthetic scroll (via `page.evaluate(() => window.scrollBy(...))`) does not reliably fire ScrollTrigger callbacks, leaving elements invisible in screenshots.

## The Workaround

Before taking a screenshot for visual verification, force-reveal all opacity-0 elements:

```js
await page.evaluate(() => {
  document.querySelectorAll('[style*="opacity: 0"]').forEach(el => {
    el.style.opacity = '1';
  });
});
```

Then take the screenshot.

## Important Caveat

This is a **screenshot verification tool only**. In a real browser, user scrolling correctly triggers ScrollTrigger and animates elements in naturally. Never apply this workaround to production code.

## Related

- [[Concepts/Theme-Aware CSS Variables]]
- [[01 - Projects/Clarence Portfolio Site]]
