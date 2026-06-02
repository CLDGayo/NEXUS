import { createContext, useCallback, useEffect, useMemo, useState } from 'react';

export const SidebarContext = createContext(null);

export function SidebarProvider({ children }) {
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem('nexus.sidebar.collapsed') === 'true',
  );

  useEffect(() => {
    localStorage.setItem('nexus.sidebar.collapsed', String(collapsed));
  }, [collapsed]);

  const toggle = useCallback(() => setCollapsed((v) => !v), []);

  const value = useMemo(
    () => ({ collapsed, toggle, setCollapsed }),
    [collapsed, toggle],
  );

  return (
    <SidebarContext.Provider value={value}>{children}</SidebarContext.Provider>
  );
}
