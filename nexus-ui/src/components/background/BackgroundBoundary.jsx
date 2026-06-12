import { Component } from 'react';

// If WebGL is unavailable or three.js throws, render nothing — the CSS pastel
// mesh in AppShell remains as the always-present fallback layer.
export default class BackgroundBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error) {
    // Non-fatal: the background is decorative. Log once for diagnostics.
    if (import.meta.env?.DEV) console.warn('LiquidBackground disabled:', error);
  }

  render() {
    if (this.state.failed) return null;
    return this.props.children;
  }
}
