import { createContext, useCallback, useEffect, useMemo, useState } from 'react';

export const SidebarContext = createContext(null);

export function SidebarProvider({ children }) {
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem('nexus.sidebar.collapsed') === 'true',
  );
  // Mobile off-canvas drawer — not persisted; closed on every load.
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    localStorage.setItem('nexus.sidebar.collapsed', String(collapsed));
  }, [collapsed]);

  const toggle = useCallback(() => setCollapsed((v) => !v), []);
  const toggleMobile = useCallback(() => setMobileOpen((v) => !v), []);

  const value = useMemo(
    () => ({ collapsed, toggle, setCollapsed, mobileOpen, setMobileOpen, toggleMobile }),
    [collapsed, toggle, mobileOpen, toggleMobile],
  );

  return (
    <SidebarContext.Provider value={value}>{children}</SidebarContext.Provider>
  );
}
