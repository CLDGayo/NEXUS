import { Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthProvider.jsx';
import RequireAuth from './components/auth/RequireAuth.jsx';
import LoginScreen from './components/auth/LoginScreen.jsx';
import AppShell from './components/layout/AppShell.jsx';

import ChatPage from './pages/ChatPage.jsx';
import DashboardPage from './pages/DashboardPage.jsx';
import DocumentsPage from './pages/DocumentsPage.jsx';
import ConversationsPage from './pages/ConversationsPage.jsx';
import LogsPage from './pages/LogsPage.jsx';
import IntegrationsPage from './pages/IntegrationsPage.jsx';
import ResourcesPage from './pages/ResourcesPage.jsx';
import SettingsPage from './pages/SettingsPage.jsx';
import ChangelogPage from './pages/ChangelogPage.jsx';

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginScreen />} />
        <Route
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
          <Route path="/" element={<Navigate to="/chat" replace />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/conversations" element={<ConversationsPage />} />
          <Route path="/logs" element={<LogsPage />} />
          <Route path="/integrations" element={<IntegrationsPage />} />
          <Route path="/resources" element={<ResourcesPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/changelog" element={<ChangelogPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/chat" replace />} />
      </Routes>
    </AuthProvider>
  );
}
