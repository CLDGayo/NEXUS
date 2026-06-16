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
import { useTranslation } from 'react-i18next';
import { useTenant } from '../hooks/useTenant.js';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/Tabs.jsx';
import MembersTab from '../components/workspace/MembersTab.jsx';
import GeneralTab from '../components/workspace/GeneralTab.jsx';
import AdvancedTab from '../components/workspace/AdvancedTab.jsx';
import UsageTab from '../components/workspace/UsageTab.jsx';

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
  const { t } = useTranslation('workspace');
  const { slug } = useParams();
  const {
    tenants,
    activeTenantId,
    setActiveTenant,
    tenantsLoading,
    refreshTenants,
  } = useTenant();
  const [tab, setTab] = useState('general');

  const tenant = tenants.find((t) => t.slug === slug);

  if (!tenant) {
    if (tenantsLoading || tenants.length === 0) {
      return (
        <div className="flex h-full items-center justify-center text-sm text-nexus-muted">
          {t('detail.loading')}
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
            {t('detail.back')}
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
                    {t('detail.active')}
                  </span>
                )}
              </div>
              <p className="text-xs text-nexus-muted">
                {tenant.slug} · {t('detail.yourRole')}{' '}
                <span className="font-medium uppercase">{tenant.role}</span>
              </p>
            </div>
          </div>
        </div>

        {!isActive && (
          <div className="flex items-center justify-between rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 dark:border-amber-500/30 dark:bg-amber-500/10">
            <p className="text-xs text-amber-800 dark:text-amber-300">
              {t('detail.notActiveBanner')}
            </p>
            <button
              type="button"
              onClick={() => setActiveTenant(tenant.id)}
              className="ml-3 shrink-0 rounded-md bg-nexus-accent px-3 py-1.5 text-xs font-medium text-white hover:opacity-90"
            >
              {t('detail.switchTo', { name: tenant.name })}
            </button>
          </div>
        )}

        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="general">{t('detail.tabs.general')}</TabsTrigger>
            <TabsTrigger value="members">{t('detail.tabs.members')}</TabsTrigger>
            <TabsTrigger value="usage">{t('detail.tabs.usage')}</TabsTrigger>
            <TabsTrigger value="advanced">{t('detail.tabs.advanced')}</TabsTrigger>
          </TabsList>

          <div className="mt-4">
            <TabsContent value="general">
              {isActive ? (
                <GeneralTab
                  tenantId={tenant.id}
                  tenant={tenant}
                  onSaved={() => refreshTenants()}
                />
              ) : (
                <PlaceholderTab
                  icon={Settings2}
                  title={t('detail.placeholder.generalTitle')}
                  copy={t('detail.placeholder.generalCopy')}
                />
              )}
            </TabsContent>

            <TabsContent value="members">
              {isActive ? (
                <MembersTab tenantId={tenant.id} />
              ) : (
                <PlaceholderTab
                  icon={Users}
                  title={t('detail.placeholder.membersTitle')}
                  copy={t('detail.placeholder.membersCopy')}
                />
              )}
            </TabsContent>

            <TabsContent value="usage">
              {isActive ? (
                <UsageTab tenantId={tenant.id} />
              ) : (
                <PlaceholderTab
                  icon={Gauge}
                  title={t('detail.placeholder.usageTitle')}
                  copy={t('detail.placeholder.usageCopy')}
                />
              )}
            </TabsContent>

            <TabsContent value="advanced">
              {isActive ? (
                <AdvancedTab
                  tenantId={tenant.id}
                  tenant={tenant}
                  onTenantChanged={() => refreshTenants()}
                />
              ) : (
                <PlaceholderTab
                  icon={ShieldAlert}
                  title={t('detail.placeholder.advancedTitle')}
                  copy={t('detail.placeholder.advancedCopy')}
                />
              )}
            </TabsContent>
          </div>
        </Tabs>
      </div>
    </div>
  );
}
