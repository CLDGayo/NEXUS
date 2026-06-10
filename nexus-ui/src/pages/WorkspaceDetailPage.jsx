import { useState } from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  Building2,
  CheckCircle2,
  Gauge,
  Settings2,
  ShieldAlert,
  Users,
} from 'lucide-react';
import { useTenant } from '../hooks/useTenant.js';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/Tabs.jsx';
import MembersTab from '../components/workspace/MembersTab.jsx';

function PlaceholderTab({ icon: Icon, title, copy }) {
  return (
    <div className="glass-card flex flex-col items-center gap-2 py-12 text-center">
      <Icon size={20} className="text-nexus-muted" />
      <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
        {title}
      </p>
      <p className="max-w-sm text-xs text-nexus-muted">{copy}</p>
    </div>
  );
}

// Phase 50 — Workspace Manager master-detail view. The detail page manages
// the workspace identified by :slug. All tenant-scoped API calls carry the
// ACTIVE tenant's X-Tenant-ID header and the backend rejects path/header
// mismatches, so managing a non-active workspace requires switching first —
// the banner below makes that explicit instead of letting calls 400.
export default function WorkspaceDetailPage() {
  const { slug } = useParams();
  const { tenants, activeTenantId, setActiveTenant, tenantsLoading } =
    useTenant();
  const [tab, setTab] = useState('members');

  const tenant = tenants.find((t) => t.slug === slug);

  if (!tenant) {
    if (tenantsLoading || tenants.length === 0) {
      return (
        <div className="flex h-full items-center justify-center text-sm text-nexus-muted">
          Loading workspace…
        </div>
      );
    }
    return <Navigate to="/settings/workspaces" replace />;
  }

  const isActive = tenant.id === activeTenantId;

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl space-y-4 p-6">
        <div className="flex items-center gap-3">
          <Link
            to="/settings/workspaces"
            className="glass-pressable inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-nexus-muted hover:text-slate-700 dark:hover:text-slate-300"
          >
            <ArrowLeft size={12} />
            Workspaces
          </Link>
        </div>

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-nexus-accent/15">
              <Building2 size={18} className="text-nexus-accent" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100">
                  {tenant.name}
                </h2>
                {isActive && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
                    <CheckCircle2 size={10} />
                    Active
                  </span>
                )}
              </div>
              <p className="text-xs text-nexus-muted">
                {tenant.slug} · your role:{' '}
                <span className="font-medium uppercase">{tenant.role}</span>
              </p>
            </div>
          </div>
        </div>

        {!isActive && (
          <div className="flex items-center justify-between rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 dark:border-amber-500/30 dark:bg-amber-500/10">
            <p className="text-xs text-amber-800 dark:text-amber-300">
              You are viewing a workspace that is not currently active. Switch
              to it to manage members and settings.
            </p>
            <button
              type="button"
              onClick={() => setActiveTenant(tenant.id)}
              className="ml-3 shrink-0 rounded-md bg-nexus-accent px-3 py-1.5 text-xs font-medium text-white hover:opacity-90"
            >
              Switch to {tenant.name}
            </button>
          </div>
        )}

        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="general">General</TabsTrigger>
            <TabsTrigger value="members">Members</TabsTrigger>
            <TabsTrigger value="usage">Usage</TabsTrigger>
            <TabsTrigger value="advanced">Advanced</TabsTrigger>
          </TabsList>

          <div className="mt-4">
            <TabsContent value="general">
              <div className="glass-card space-y-3 p-5">
                <div className="flex items-center gap-2">
                  <Settings2 size={14} className="text-nexus-accent" />
                  <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                    General
                  </h3>
                </div>
                <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
                  <div>
                    <dt className="text-xs text-nexus-muted">Name</dt>
                    <dd className="font-medium text-slate-800 dark:text-slate-100">
                      {tenant.name}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-nexus-muted">Slug</dt>
                    <dd className="font-medium text-slate-800 dark:text-slate-100">
                      {tenant.slug}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-nexus-muted">Created</dt>
                    <dd className="font-medium text-slate-800 dark:text-slate-100">
                      {tenant.created_at
                        ? new Date(tenant.created_at).toLocaleDateString()
                        : '—'}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-nexus-muted">Members</dt>
                    <dd className="font-medium text-slate-800 dark:text-slate-100">
                      {tenant.member_count ?? '—'}
                    </dd>
                  </div>
                </dl>
                <p className="text-xs text-nexus-muted">
                  Rename, custom logo, and slug management arrive in an
                  upcoming update.
                </p>
              </div>
            </TabsContent>

            <TabsContent value="members">
              {isActive ? (
                <MembersTab tenantId={tenant.id} />
              ) : (
                <PlaceholderTab
                  icon={Users}
                  title="Switch to this workspace to manage members"
                  copy="Member management operates on the active workspace. Use the switch banner above."
                />
              )}
            </TabsContent>

            <TabsContent value="usage">
              <PlaceholderTab
                icon={Gauge}
                title="Usage dashboard coming soon"
                copy="Vector chunks, message volume, and document counts for this workspace will appear here."
              />
            </TabsContent>

            <TabsContent value="advanced">
              <PlaceholderTab
                icon={ShieldAlert}
                title="Advanced controls coming soon"
                copy="Archive, ownership transfer, and workspace deletion will live here, restricted to owners."
              />
            </TabsContent>
          </div>
        </Tabs>
      </div>
    </div>
  );
}
