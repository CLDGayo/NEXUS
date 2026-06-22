import { LogOut } from 'lucide-react';
import { CORE_NAV, OWNER_NAV, MANAGER_NAV, TRAILING_NAV, ADMIN_NAV_ITEM } from '../../lib/nav.js';

/**
 * Build the command list for the Cmd+K palette.
 * Role gates: OWNER_NAV only if isOwner; MANAGER_NAV if canManage
 * (owner or admin, Phase 50); ADMIN_NAV_ITEM only if isSuperuser.
 * /graph is auto-derived from CORE_NAV (added Phase 43).
 *
 * `labelKey` is an i18n key (common namespace); CommandPalette resolves it via
 * t() at render so the palette follows the active language.
 *
 * @param {{ isOwner: boolean, canManage: boolean, isSuperuser: boolean }} flags
 * @returns {{ id: string, labelKey: string, Icon: React.ComponentType, kind: string, to?: string }[]}
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
    labelKey: item.labelKey,
    Icon: item.Icon,
    kind: 'nav',
    to: item.to,
    // Phase 68 — external nav items (Docs) open in a new tab from the palette.
    external: !!item.external,
  }));

  const actionCommands = [
    { id: 'logout', labelKey: 'command.signOut', Icon: LogOut, kind: 'action' },
  ];

  return [...navCommands, ...actionCommands];
}
