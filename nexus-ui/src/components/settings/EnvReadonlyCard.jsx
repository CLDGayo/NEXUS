export default function EnvReadonlyCard({ env }) {
  const entries = Object.entries(env || {});
  return (
    <section className="rounded-xl border border-nexus-border bg-white p-5 shadow-sm">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-slate-800">Environment (read-only)</h3>
        <p className="text-xs text-nexus-muted">Configured via env vars on the host. Edit via systemd EnvironmentFile + restart.</p>
      </div>
      <div className="divide-y divide-nexus-border">
        {entries.length === 0 ? (
          <div className="py-2 text-xs text-nexus-muted">No env vars exposed.</div>
        ) : (
          entries.map(([k, v]) => (
            <div key={k} className="grid grid-cols-1 gap-1 py-2 sm:grid-cols-3 sm:gap-2">
              <div className="font-mono text-xs font-semibold text-slate-700">{k}</div>
              <div className="break-all rounded bg-slate-50 px-2 py-1 font-mono text-[11px] text-slate-600 sm:col-span-2">
                {v || <span className="text-slate-400">not set</span>}
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
