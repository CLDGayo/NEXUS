import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer } from 'recharts';
import { useTranslation } from 'react-i18next';

function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export default function QueryVolumeChart({ data }) {
  const { t } = useTranslation('dashboard');
  const series = Array.isArray(data) ? data : [];
  return (
    <section className="glass-card p-4">
      <div className="mb-3 text-[11px] font-semibold uppercase tracking-wide text-nexus-muted">{t('charts.queryVolume')}</div>
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={series} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={formatDate}
              tick={{ fontSize: 10, fill: '#64748b' }}
              stroke="#cbd5e1"
            />
            <YAxis tick={{ fontSize: 10, fill: '#64748b' }} stroke="#cbd5e1" allowDecimals={false} />
            <Tooltip
              labelFormatter={formatDate}
              contentStyle={{ fontSize: '11px', borderRadius: '8px', border: '1px solid #e2e8f0' }}
            />
            <Line type="monotone" dataKey="queries" stroke="#2563eb" strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
