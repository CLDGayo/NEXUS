import { lazy, Suspense } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import Sidebar, { MobileSidebar } from './Sidebar.jsx';
import PageHeader from './PageHeader.jsx';
import { SidebarProvider } from '../../context/SidebarProvider.jsx';
import { useCommandPalette } from '../../hooks/useCommandPalette.js';
import CommandPalette from '../command/CommandPalette.jsx';
import BackgroundBoundary from '../background/BackgroundBoundary.jsx';

// Lazy so three.js lands in its own chunk and never blocks first paint.
const LiquidBackground = lazy(() => import('../background/LiquidBackground.jsx'));

const TITLES = {
  '/dashboard':           'Dashboard',
  '/documents':           'Documents',
  '/chat':                'Chat',
  '/conversations':       'Conversations',
  '/logs':                'Logs',
  '/integrations':        'Integrations',
  '/resources':           'Resources',
  '/products':            'Products',
  '/products/new':        'New product',
  '/settings':            'Settings',
  '/settings/workspaces': 'Workspaces',
  '/changelog':           "What's New",
  '/profile':             'Profile',
  '/admin/users':         'Admin · Users',
};

// Phase 32.1 — regex fallbacks for parametric routes that exact-match
// can't cover. First match wins; falls through to "NEXUS" when nothing
// hits.
const MATCHERS = [
  [/^\/products\/[^/]+$/, 'Product'],
];

function resolveTitle(pathname) {
  if (TITLES[pathname]) return TITLES[pathname];
  for (const [re, title] of MATCHERS) {
    if (re.test(pathname)) return title;
  }
  return 'NEXUS';
}

function ShellInner() {
  const { pathname } = useLocation();
  const title = resolveTitle(pathname);
  const { open, setOpen } = useCommandPalette();

  return (
    <div className="relative h-screen flex overflow-hidden text-slate-900 dark:text-slate-100">
      {/* Ambient pastel mesh (fixed z-0) — slow-drifting mint / blush / sky blobs.
          Doubles as the reduced-motion + no-WebGL fallback for the 3D liquid
          background. Body holds the cream/ink base color BEHIND this; translucent
          glass content (z-10) refracts it. Freezes under reduced-motion. */}
      <div aria-hidden className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
        <div className="absolute -left-[10%] -top-[15%] h-[55vh] w-[55vh] animate-mesh-drift rounded-full bg-[radial-gradient(circle,rgba(191,232,212,0.55),transparent_70%)] blur-3xl dark:bg-[radial-gradient(circle,rgba(91,124,250,0.30),transparent_70%)]" />
        <div className="absolute right-[-12%] top-[8%] h-[50vh] w-[50vh] animate-mesh-drift rounded-full bg-[radial-gradient(circle,rgba(246,212,221,0.50),transparent_70%)] blur-3xl [animation-delay:-7s] dark:bg-[radial-gradient(circle,rgba(157,180,255,0.20),transparent_70%)]" />
        <div className="absolute bottom-[-18%] left-[25%] h-[55vh] w-[55vh] animate-mesh-drift rounded-full bg-[radial-gradient(circle,rgba(207,224,245,0.55),transparent_70%)] blur-3xl [animation-delay:-14s] dark:bg-[radial-gradient(circle,rgba(191,232,212,0.16),transparent_70%)]" />
      </div>

      {/* 3D liquid orbs — fixed z-0 above the mesh, below all glass content.
          Falls back to the mesh alone if WebGL is unavailable or three.js fails. */}
      <BackgroundBoundary>
        <Suspense fallback={null}>
          <LiquidBackground />
        </Suspense>
      </BackgroundBoundary>

      {/* Faint scrim over the orbs (below content) — calms the saturated 3D
          field so frosted glass + text keep contrast without hiding the liquid. */}
      <div aria-hidden className="pointer-events-none fixed inset-0 z-0 bg-nexus-cream/35 backdrop-blur-md dark:bg-nexus-ink/45" />

      <div className="relative z-10 flex flex-1 min-w-0">
        <Sidebar />
        <MobileSidebar />

        <main className="flex-1 flex flex-col min-w-0">
          <PageHeader title={title} onOpenCommand={() => setOpen(true)} />
          <div className="flex-1 min-h-0 overflow-hidden">
            <Outlet />
          </div>
        </main>
      </div>

      <CommandPalette open={open} onOpenChange={setOpen} />
    </div>
  );
}

export default function AppShell() {
  return (
    <SidebarProvider>
      <ShellInner />
    </SidebarProvider>
  );
}
