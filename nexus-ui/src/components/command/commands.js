import { LogOut } from 'lucide-react';
import { CORE_NAV, OWNER_NAV, MANAGER_NAV, TRAILING_NAV, ADMIN_NAV_ITEM } from '../../lib/nav.js';

/**
 * Build the command list for the Cmd+K palette.
 * Role gates: OWNER_NAV only if isOwner; MANAGER_NAV if canManage
 * (owner or admin, Phase 50); ADMIN_NAV_ITEM only if isSuperuser.
 * /graph is auto-derived from CORE_NAV (added Phase 43).
 *
 * @param {{ isOwner: boolean, canManage: boolean, isSuperuser: boolean }} flags
 * @returns {{ id: string, label: string, Icon: React.ComponentType, kind: string, to?: string }[]}
 */
export function buildCommands({ isOwner, canManage, isSuperuser }) {
  const navCommands = [
    ...CORE_NAV,
    ...(isOwner ? OWNER_NAV : []),
    ...(canManage ? MANAGER_NAV : []),
    ...TRAILING_NAV,
    ...(isSuperuser ? [ADMIN_NAV_ITEM] : []),
  ].map((item) => ({
    id: item.to,
    label: item.label,
    Icon: item.Icon,
    kind: 'nav',
    to: item.to,
  }));

  const actionCommands = [
    { id: 'logout', label: 'Sign out', Icon: LogOut, kind: 'action' },
  ];

  return [...navCommands, ...actionCommands];
}
