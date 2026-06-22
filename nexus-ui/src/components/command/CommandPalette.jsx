import { useEffect, useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../../hooks/useAuth.js';
import { useTenant } from '../../hooks/useTenant.js';
import { buildCommands } from './commands.js';

export default function CommandPalette({ open, onOpenChange }) {
  const { t } = useTranslation();
  const { isSuperuser, logout } = useAuth();
  const { activeTenantRole, canManage } = useTenant();
  const navigate = useNavigate();

  const isOwner = activeTenantRole === 'owner';
  // Resolve each command's i18n key to its label up front so both the filter
  // and the rendered row use the localized text.
  const allCommands = buildCommands({ isOwner, canManage, isSuperuser }).map((cmd) => ({
    ...cmd,
    label: t(cmd.labelKey),
  }));

  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef(null);

  // Reset state whenever the palette opens or closes
  useEffect(() => {
    if (open) {
      setQuery('');
      setActiveIndex(0);
    }
  }, [open]);

  // Reset active index whenever the query changes
  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  const filtered = allCommands.filter((cmd) =>
    cmd.label.toLowerCase().includes(query.toLowerCase()),
  );

  function runCommand(cmd) {
    if (cmd.kind === 'nav') {
      if (cmd.external) {
        window.open(cmd.to, '_blank', 'noopener,noreferrer');
      } else {
        navigate(cmd.to);
      }
    } else if (cmd.kind === 'action' && cmd.id === 'logout') {
      logout();
    }
    onOpenChange(false);
  }

  function handleKeyDown(e) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const cmd = filtered[activeIndex];
      if (cmd) runCommand(cmd);
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="glass-overlay" />
        <Dialog.Content
          className="fixed left-1/2 top-24 z-50 w-full max-w-lg -translate-x-1/2 glass-dialog glass-rise overflow-hidden focus:outline-none"
          aria-describedby={undefined}
          onOpenAutoFocus={(e) => {
            // Manually focus the input; prevent Radix from focusing the content div
            e.preventDefault();
            inputRef.current?.focus();
          }}
        >
          <Dialog.Title className="sr-only">{t('command.title')}</Dialog.Title>

          {/* Search input */}
          <div className="flex items-center border-b border-white/40 px-4">
            <input
              ref={inputRef}
              type="text"
              className="flex-1 bg-transparent py-4 text-sm text-slate-900 dark:text-slate-100 placeholder:text-slate-400 focus:outline-none"
              placeholder={t('command.placeholder')}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
            />
            <kbd className="hidden shrink-0 rounded border border-slate-200 dark:border-slate-700/50 bg-white/60 px-1.5 py-0.5 text-[10px] text-slate-500 dark:text-slate-400 sm:inline-block">
              ESC
            </kbd>
          </div>

          {/* Command list */}
          <div className="max-h-72 overflow-y-auto p-2">
            {filtered.length === 0 ? (
              <div className="px-3 py-6 text-center text-sm text-slate-400">
                {t('command.noResults')}
              </div>
            ) : (
              filtered.map((cmd, idx) => {
                const isActive = idx === activeIndex;
                return (
                  <button
                    key={cmd.id}
                    type="button"
                    className={[
                      'glass-pressable flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-left transition-colors',
                      isActive
                        ? 'bg-nexus-accent/12 text-nexus-accent shadow-[inset_0_1px_0_0_rgba(255,255,255,0.4)] dark:bg-nexus-accent/20'
                        : 'text-slate-700 dark:text-slate-300 hover:bg-white/50 dark:hover:bg-white/5',
                    ].join(' ')}
                    onMouseEnter={() => setActiveIndex(idx)}
                    onClick={() => runCommand(cmd)}
                  >
                    <cmd.Icon size={16} className="shrink-0" />
                    <span>{cmd.label}</span>
                  </button>
                );
              })
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
