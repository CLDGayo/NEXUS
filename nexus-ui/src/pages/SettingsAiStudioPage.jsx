import { useCallback, useEffect, useMemo, useState } from 'react';
import { Sparkles, MessageSquareText, ToggleRight, SlidersHorizontal } from 'lucide-react';
import { api } from '../lib/api.js';
import { usePageMountTimeline } from '../hooks/usePageMountTimeline.js';
import { useTactilePress } from '../hooks/useTactilePress.js';
import ScenarioPromptsTabs from '../components/aistudio/ScenarioPromptsTabs.jsx';
import NodeTogglesPanel from '../components/aistudio/NodeTogglesPanel.jsx';
import ModelParamsPanel from '../components/aistudio/ModelParamsPanel.jsx';

// Phase 49 — Prompt Studio. Owner-only editor for the tenant's ai_settings
// (scenario_prompts persona overlays, active_nodes toggles, model_params).
// GET on mount, PUT the dirty sub-objects on save.
export default function SettingsAiStudioPage() {
  const pageRef = usePageMountTimeline();
  const saveRef = useTactilePress();

  const [settings, setSettings] = useState(null);
  const [initial, setInitial] = useState(null);
  const [availableModels, setAvailableModels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    api
      .get('/workspace/ai-settings')
      .then((d) => {
        const { available_models = [], ...blob } = d;
        setSettings(blob);
        setInitial(JSON.stringify(blob));
        setAvailableModels(available_models);
        setError(null);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const dirty = useMemo(
    () => settings != null && JSON.stringify(settings) !== initial,
    [settings, initial],
  );

  const patchSection = (section, key, val) =>
    setSettings((prev) => ({
      ...prev,
      [section]: { ...(prev?.[section] || {}), [key]: val },
    }));

  const save = async () => {
    if (!settings || saving) return;
    setSaving(true);
    setStatus(null);
    setError(null);
    try {
      const updated = await api.put('/workspace/ai-settings', {
        scenario_prompts: settings.scenario_prompts,
        active_nodes: settings.active_nodes,
        model_params: settings.model_params,
      });
      const { available_models = [], ...blob } = updated;
      setSettings(blob);
      setInitial(JSON.stringify(blob));
      setAvailableModels(available_models);
      setStatus('Saved.');
    } catch (err) {
      setError(err.message || 'Save failed.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto">
      <div ref={pageRef} className="mx-auto max-w-4xl space-y-4 p-6">
        <div data-animate className="flex items-center justify-between">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-700">
              <Sparkles size={15} className="text-nexus-accent" />
              AI Studio
            </h2>
            <p className="text-xs text-nexus-muted">
              Tune this workspace&apos;s persona, active nodes, and model parameters.
            </p>
          </div>
          <button
            ref={saveRef}
            onClick={save}
            disabled={!dirty || saving}
            className="rounded-lg bg-nexus-accent px-4 py-2 text-sm font-medium text-white shadow-sm transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>

        {loading && (
          <div className="glass-pane p-6 text-center text-sm text-nexus-muted">
            Loading AI settings…
          </div>
        )}
        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            {error}
          </div>
        )}
        {status && !error && (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">
            {status}
          </div>
        )}

        {!loading && settings && (
          <>
            <section data-animate className="space-y-2">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                <MessageSquareText size={14} className="text-nexus-accent" />
                Scenario Prompts
              </h3>
              <ScenarioPromptsTabs
                value={settings.scenario_prompts}
                onChange={(k, v) => patchSection('scenario_prompts', k, v)}
              />
            </section>

            <section data-animate className="space-y-2">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                <ToggleRight size={14} className="text-nexus-accent" />
                Active Nodes
              </h3>
              <NodeTogglesPanel
                value={settings.active_nodes}
                onChange={(k, v) => patchSection('active_nodes', k, v)}
              />
            </section>

            <section data-animate className="space-y-2">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                <SlidersHorizontal size={14} className="text-nexus-accent" />
                Model Parameters
              </h3>
              <ModelParamsPanel
                value={settings.model_params}
                availableModels={availableModels}
                onChange={(k, v) => patchSection('model_params', k, v)}
              />
            </section>
          </>
        )}
      </div>
    </div>
  );
}
