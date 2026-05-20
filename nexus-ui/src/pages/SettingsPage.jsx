import { useCallback, useEffect, useState } from 'react';
import { api } from '../lib/api.js';
import TunableSettingsForm from '../components/settings/TunableSettingsForm.jsx';
import EnvReadonlyCard from '../components/settings/EnvReadonlyCard.jsx';
import PasswordCard from '../components/settings/PasswordCard.jsx';
import JwtRotateCard from '../components/settings/JwtRotateCard.jsx';

export default function SettingsPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    api.get('/settings')
      .then((d) => { setData(d); setError(null); })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl space-y-4 p-6">
        <div>
          <h2 className="text-sm font-semibold text-slate-700">Settings</h2>
          <p className="text-xs text-nexus-muted">
            Tunables, environment, auth.
          </p>
        </div>

        {loading && (
          <div className="rounded-xl border border-nexus-border bg-white p-6 text-center text-sm text-nexus-muted shadow-sm">
            Loading settings…
          </div>
        )}
        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
        )}

        {!loading && !error && data && (
          <>
            <TunableSettingsForm
              schema={data.schema}
              values={data.values}
              onSaved={load}
            />
            <EnvReadonlyCard env={data.env_readonly} />
            <PasswordCard />
            <JwtRotateCard />
          </>
        )}
      </div>
    </div>
  );
}
