import { LogOut } from 'lucide-react';
import { CORE_NAV, OWNER_NAV, TRAILING_NAV, ADMIN_NAV_ITEM } from '../../lib/nav.js';

/**
 * Build the command list for the Cmd+K palette.
 * Role gates: OWNER_NAV only if isOwner; ADMIN_NAV_ITEM only if isSuperuser.
 * No /graph command — that route lands in Phase 43.
 *
 * @param {{ isOwner: boolean, isSuperuser: boolean }} flags
 * @returns {{ id: string, label: string, Icon: React.ComponentType, kind: string, to?: string }[]}
 */
export function buildCommands({ isOwner, isSuperuser }) {
  const navCommands = [
    ...CORE_NAV,
    ...(isOwner ? OWNER_NAV : []),
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
