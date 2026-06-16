# Dark Mode

NEXUS supports light, dark, and system-preference modes. Selection persists in `localStorage`.

---

## ThemeProvider

`ThemeProvider.jsx` injects a `data-theme` attribute on `<html>`:

```jsx
const [theme, setTheme] = useState(
  () => localStorage.getItem('nexus_theme') || 'system'
);

useEffect(() => {
  const resolved = theme === 'system'
    ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    : theme;
  document.documentElement.setAttribute('data-theme', resolved);
  localStorage.setItem('nexus_theme', theme);
}, [theme]);
```

---

## CSS Variables

Glass tokens adapt per theme via CSS `[data-theme]` selectors:

```css
[data-theme="light"] {
  --glass-bg: rgba(255, 255, 255, 0.12);
  --glass-border: rgba(255, 255, 255, 0.18);
  --glass-blur: 12px;
}

[data-theme="dark"] {
  --glass-bg: rgba(0, 0, 0, 0.25);
  --glass-border: rgba(255, 255, 255, 0.08);
  --glass-blur: 16px;
}
```

---

## Theme Toggle

`useTheme()` hook exposes `theme` and `setTheme`. The toggle is in the top bar:

```jsx
const { theme, setTheme } = useTheme();
const options = ['light', 'dark', 'system'];
```

---

## System Preference Sync

When `theme = "system"`, NEXUS listens for OS preference changes:

```javascript
const mq = window.matchMedia('(prefers-color-scheme: dark)');
mq.addEventListener('change', recompute);
```

---

## Related Docs

- [Design System](design-system.md)
- [Component Architecture](component-architecture.md)
