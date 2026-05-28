import { useContext } from 'react';
import { TenantContext } from '../context/TenantProvider.jsx';

export function useTenant() {
  const ctx = useContext(TenantContext);
  if (ctx == null) {
    throw new Error('useTenant must be used inside <TenantProvider>');
  }
  return ctx;
}
