import { FileText, Layers, Clock } from 'lucide-react';
import { useTranslation } from 'react-i18next';

function Card({ icon: Icon, label, value, sub }) {
  return (
    <div className="flex items-center gap-3 glass-card px-4 py-3 shadow-sm">
      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50 text-nexus-accent">
        <Icon size={16} />
      </div>
      <div className="min-w-0">
        <div className="text-[11px] font-medium uppercase tracking-wide text-nexus-muted">
          {label}
        </div>
        <div className="text-lg font-semibold text-slate-800 dark:text-slate-100 leading-tight">{value}</div>
        {sub && <div className="text-[11px] text-nexus-muted truncate">{sub}</div>}
      </div>
    </div>
  );
}

export default function SummaryCards({ totalNotes, totalChunks, lastSync, chunksAvailable }) {
  const { t } = useTranslation('documents');
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <Card icon={FileText} label={t('summary.totalNotes')} value={totalNotes.toLocaleString()} />
      <Card
        icon={Layers}
        label={t('summary.vectorChunks')}
        value={chunksAvailable ? totalChunks.toLocaleString() : '—'}
        sub={chunksAvailable ? null : t('summary.qdrantUnreachable')}
      />
      <Card
        icon={Clock}
        label={t('summary.lastSync')}
        value={lastSync ? new Date(lastSync).toLocaleTimeString() : '—'}
        sub={lastSync ? new Date(lastSync).toLocaleDateString() : null}
      />
    </div>
  );
}
