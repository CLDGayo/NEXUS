import { lazy, Suspense } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import * as Tooltip from '@radix-ui/react-tooltip';
import { AuthProvider } from './context/AuthProvider.jsx';
import { TenantProvider } from './context/TenantProvider.jsx';
import RequireAuth from './components/auth/RequireAuth.jsx';
import RequireOwner from './components/auth/RequireOwner.jsx';
import RequireManager from './components/auth/RequireManager.jsx';
import RequireSuperuser from './components/auth/RequireSuperuser.jsx';
import RequireTenant from './components/auth/RequireTenant.jsx';
import LoginScreen from './components/auth/LoginScreen.jsx';
import AppShell from './components/layout/AppShell.jsx';

import ChatPage from './pages/ChatPage.jsx';
import DashboardPage from './pages/DashboardPage.jsx';
import DocumentsPage from './pages/DocumentsPage.jsx';
import ConversationsPage from './pages/ConversationsPage.jsx';
import LogsPage from './pages/LogsPage.jsx';
import IntegrationsPage from './pages/IntegrationsPage.jsx';
import FlowsPage from './pages/FlowsPage.jsx';
import ResourcesPage from './pages/ResourcesPage.jsx';
import ProductsDashboardPage from './pages/ProductsDashboardPage.jsx';
import ProductEditPage from './pages/ProductEditPage.jsx';
import SettingsPage from './pages/SettingsPage.jsx';
import SettingsWorkspacesPage from './pages/SettingsWorkspacesPage.jsx';
import WorkspaceDetailPage from './pages/WorkspaceDetailPage.jsx';
import SettingsAiStudioPage from './pages/SettingsAiStudioPage.jsx';
import ChangelogPage from './pages/ChangelogPage.jsx';
import WhatsNewPage from './pages/WhatsNewPage.jsx';
import ProfilePage from './pages/ProfilePage.jsx';
import AdminUsersPage from './pages/AdminUsersPage.jsx';
import JoinWorkspacePage from './pages/JoinWorkspacePage.jsx';
import OAuthCallback from './pages/OAuthCallback.jsx';
import DocsPage from './pages/DocsPage.jsx';
import GlassSpinner from './components/graph/GlassSpinner.jsx';

// GraphPage is lazy-loaded to code-split react-force-graph-2d + d3-force
// out of the main bundle. All other pages remain static imports.
const GraphPage = lazy(() => import('./pages/GraphPage.jsx'));

// Phase 58 — FlowBuilderPage is lazy-loaded to code-split @xyflow/react
// (React Flow canvas) out of the main bundle. FlowsPage (list) stays static.
const FlowBuilderPage = lazy(() => import('./pages/FlowBuilderPage.jsx'));

export default function App() {
  return (
    <AuthProvider>
      <TenantProvider>
        <Tooltip.Provider delayDuration={0}>
        <Routes>
          <Route path="/login" element={<LoginScreen />} />
          {/* Phase 56 — Google OAuth landing pad. Public (no RequireAuth):
              the user has no Nexus session yet when Google redirects here. */}
          <Route path="/auth/callback" element={<OAuthCallback />} />
          <Route
            element={
              <RequireAuth>
                <RequireTenant>
                  <AppShell />
                </RequireTenant>
              </RequireAuth>
            }
          >
            <Route path="/" element={<Navigate to="/chat" replace />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/documents" element={<DocumentsPage />} />
            <Route path="/conversations" element={<ConversationsPage />} />
            <Route path="/logs" element={<LogsPage />} />
            <Route path="/resources" element={<ResourcesPage />} />
            <Route
              path="/graph"
              element={
                <Suspense fallback={<GlassSpinner />}>
                  <GraphPage />
                </Suspense>
              }
            />
            <Route element={<RequireOwner />}>
              <Route path="/products" element={<ProductsDashboardPage />} />
              <Route path="/products/:id" element={<ProductEditPage />} />
            </Route>
            {/* Phase 50 — settings are manager-class (owner or admin). */}
            <Route element={<RequireManager />}>
              {/* Integrations is manager-class — the whole /api/integrations
                  surface is require_manager. Guarding here bounces plain
                  members to /chat instead of looping the workspace picker. */}
              <Route path="/integrations" element={<IntegrationsPage />} />
              {/* Phase 58 — NEXUS Flow visual builder (manager-class). */}
              <Route path="/flows" element={<FlowsPage />} />
              <Route
                path="/flows/:id"
                element={
                  <Suspense fallback={<GlassSpinner />}>
                    <FlowBuilderPage />
                  </Suspense>
                }
              />
              <Route path="/settings" element={<SettingsPage />} />
              <Route
                path="/settings/ai-studio"
                element={<SettingsAiStudioPage />}
              />
              <Route
                path="/settings/workspaces"
                element={<SettingsWorkspacesPage />}
              />
              <Route
                path="/settings/workspaces/:slug"
                element={<WorkspaceDetailPage />}
              />
            </Route>
            <Route path="/docs" element={<DocsPage />} />
            <Route path="/docs/*" element={<DocsPage />} />
            <Route path="/whats-new" element={<WhatsNewPage />} />
            <Route path="/changelog" element={<ChangelogPage />} />
            <Route path="/profile" element={<ProfilePage />} />
            <Route
              path="/admin/users"
              element={
                <RequireSuperuser>
                  <AdminUsersPage />
                </RequireSuperuser>
              }
            />
          </Route>
          {/* Phase 51 — /join is outside RequireTenant so users with zero
              workspaces can still accept an invite. RequireAuth still guards
              it so unauthed visitors bounce to /login with state preserved. */}
          <Route
            path="/join"
            element={
              <RequireAuth>
                <JoinWorkspacePage />
              </RequireAuth>
            }
          />
          <Route path="*" element={<Navigate to="/chat" replace />} />
        </Routes>
        </Tooltip.Provider>
      </TenantProvider>
    </AuthProvider>
  );
}
