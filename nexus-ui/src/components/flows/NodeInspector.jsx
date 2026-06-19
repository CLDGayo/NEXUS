import { useCallback } from 'react';
import { useReactFlow } from '@xyflow/react';
import { X, Plus, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

/**
 * Slugify a label into a machine-safe id.
 * @param {string} label
 * @returns {string}
 */
function slugify(label) {
  return label
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    || 'intent';
}

/**
 * Shared field row wrapper.
 */
function Field({ label, children }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
        {label}
      </label>
      {children}
    </div>
  );
}

/**
 * Shared text input.
 */
function TextInput({ value, onChange, placeholder, className = '' }) {
  return (
    <input
      type="text"
      value={value || ''}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className={`w-full rounded-lg border border-white/60 bg-white/55 px-2.5 py-1.5 text-xs text-slate-800 outline-none placeholder:text-slate-400 focus:border-nexus-accent dark:border-white/10 dark:bg-white/5 dark:text-slate-100 ${className}`}
    />
  );
}

/**
 * Shared textarea.
 */
function TextArea({ value, onChange, placeholder, rows = 3 }) {
  return (
    <textarea
      value={value || ''}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      rows={rows}
      className="w-full rounded-lg border border-white/60 bg-white/55 px-2.5 py-1.5 text-xs text-slate-800 outline-none placeholder:text-slate-400 focus:border-nexus-accent dark:border-white/10 dark:bg-white/5 dark:text-slate-100 resize-none"
    />
  );
}

/**
 * Shared select.
 */
function Select({ value, onChange, children }) {
  return (
    <select
      value={value || ''}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded-lg border border-white/60 bg-white/55 px-2.5 py-1.5 text-xs text-slate-800 outline-none focus:border-nexus-accent dark:border-white/10 dark:bg-white/5 dark:text-slate-100"
    >
      {children}
    </select>
  );
}

// ---------------------------------------------------------------------------
// Per-type inspector panels
// ---------------------------------------------------------------------------

function CommentTriggerInspector({ data, patch }) {
  const { t } = useTranslation('flows');
  return (
    <>
      <Field label={t('inspector.keyword')}>
        <TextInput
          value={data.keyword}
          onChange={(v) => patch({ keyword: v })}
          placeholder={t('inspector.keywordPlaceholder')}
        />
      </Field>
      <Field label={t('inspector.matchType')}>
        <Select value={data.matchType} onChange={(v) => patch({ matchType: v })}>
          <option value="exact">{t('nodes.commentTrigger.matchExact')}</option>
          <option value="contains">{t('nodes.commentTrigger.matchContains')}</option>
          <option value="any">{t('nodes.commentTrigger.matchAny')}</option>
        </Select>
      </Field>
    </>
  );
}

function DmTriggerInspector({ data, patch }) {
  const { t } = useTranslation('flows');
  return (
    <Field label={t('inspector.keyword')}>
      <TextInput
        value={data.keyword}
        onChange={(v) => patch({ keyword: v })}
        placeholder={t('inspector.keywordPlaceholder')}
      />
    </Field>
  );
}

function ConditionInspector({ data, patch }) {
  const { t } = useTranslation('flows');
  return (
    <>
      <Field label={t('inspector.variable')}>
        <TextInput
          value={data.variable}
          onChange={(v) => patch({ variable: v })}
          placeholder={t('inspector.variablePlaceholder')}
        />
      </Field>
      <Field label={t('inspector.operator')}>
        <Select value={data.operator} onChange={(v) => patch({ operator: v })}>
          <option value="eq">{t('inspector.opEq')}</option>
          <option value="neq">{t('inspector.opNeq')}</option>
          <option value="contains">{t('inspector.opContains')}</option>
          <option value="exists">{t('inspector.opExists')}</option>
        </Select>
      </Field>
      {data.operator !== 'exists' && (
        <Field label={t('inspector.value')}>
          <TextInput
            value={data.value}
            onChange={(v) => patch({ value: v })}
            placeholder={t('inspector.valuePlaceholder')}
          />
        </Field>
      )}
    </>
  );
}

function SendMessageInspector({ data, patch }) {
  const { t } = useTranslation('flows');
  return (
    <Field label={t('inspector.message')}>
      <TextArea
        value={data.message}
        onChange={(v) => patch({ message: v })}
        placeholder={t('inspector.messagePlaceholder')}
        rows={4}
      />
    </Field>
  );
}

function WaitForInputInspector({ data, patch }) {
  const { t } = useTranslation('flows');
  return (
    <>
      <Field label={t('inspector.prompt')}>
        <TextArea
          value={data.prompt}
          onChange={(v) => patch({ prompt: v })}
          placeholder={t('inspector.promptPlaceholder')}
        />
      </Field>
      <Field label={t('inspector.captureVariable')}>
        <TextInput
          value={data.captureVariable || data.variable}
          onChange={(v) => patch({ captureVariable: v, variable: v })}
          placeholder={t('inspector.captureVariablePlaceholder')}
        />
      </Field>
      <Field label={t('inspector.validation')}>
        <TextInput
          value={data.validation}
          onChange={(v) => patch({ validation: v })}
          placeholder={t('inspector.validationPlaceholder')}
        />
      </Field>
    </>
  );
}

function AiRouterInspector({ data, patch, nodeId, setEdges }) {
  const { t } = useTranslation('flows');
  const intents = Array.isArray(data.intents) ? data.intents : [];

  function updateIntents(newIntents) {
    patch({ intents: newIntents });
    // Drop edges whose sourceHandle no longer exists in intents or fallback.
    const validHandles = new Set([
      ...newIntents.map((i) => i.id),
      data.fallbackHandle || 'other',
    ]);
    setEdges((eds) =>
      eds.filter(
        (e) => e.source !== nodeId || validHandles.has(e.sourceHandle),
      ),
    );
  }

  function addIntent() {
    const newIntent = { id: `intent-${Date.now()}`, label: '' };
    updateIntents([...intents, newIntent]);
  }

  function removeIntent(idx) {
    updateIntents(intents.filter((_, i) => i !== idx));
  }

  function updateIntentLabel(idx, label) {
    const updated = intents.map((it, i) =>
      i === idx ? { ...it, label, id: slugify(label) || it.id } : it,
    );
    updateIntents(updated);
  }

  return (
    <>
      {/* Intents list */}
      <Field label={t('inspector.intents')}>
        <div className="flex flex-col gap-1.5">
          {intents.map((intent, idx) => (
            <div key={intent.id} className="flex items-center gap-1.5">
              <TextInput
                value={intent.label}
                onChange={(v) => updateIntentLabel(idx, v)}
                placeholder={t('inspector.intentLabelPlaceholder')}
                className="flex-1"
              />
              <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[9px] text-slate-500 dark:bg-white/10 dark:text-slate-400">
                {intent.id}
              </span>
              <button
                type="button"
                onClick={() => removeIntent(idx)}
                className="shrink-0 text-red-400 hover:text-red-600"
                aria-label={t('inspector.removeIntent')}
              >
                <Trash2 size={11} />
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={addIntent}
            className="mt-0.5 flex items-center gap-1 text-[10px] font-medium text-nexus-accent hover:underline"
          >
            <Plus size={11} />
            {t('inspector.addIntent')}
          </button>
        </div>
      </Field>

      {/* Input variable */}
      <Field label={t('inspector.inputVariable')}>
        <TextInput
          value={data.inputVariable}
          onChange={(v) => patch({ inputVariable: v })}
          placeholder="_input"
        />
      </Field>

      {/* Fallback handle */}
      <Field label={t('inspector.fallbackHandle')}>
        <TextInput
          value={data.fallbackHandle}
          onChange={(v) => patch({ fallbackHandle: v })}
          placeholder="other"
        />
      </Field>
    </>
  );
}

function PauseInspector({ data, patch }) {
  const { t } = useTranslation('flows');
  return (
    <>
      <Field label={t('inspector.durationSeconds')}>
        <input
          type="number"
          min={60}
          step={3600}
          value={data.durationSeconds ?? 86400}
          onChange={(e) => patch({ durationSeconds: Number(e.target.value) })}
          className="w-full rounded-lg border border-white/60 bg-white/55 px-2.5 py-1.5 text-xs text-slate-800 outline-none focus:border-nexus-accent dark:border-white/10 dark:bg-white/5 dark:text-slate-100"
        />
        <span className="text-[10px] text-nexus-muted">
          {t('inspector.durationHint', {
            hours: Math.round((data.durationSeconds ?? 86400) / 3600),
          })}
        </span>
      </Field>
      <Field label={t('inspector.handoffMessage')}>
        <TextArea
          value={data.message}
          onChange={(v) => patch({ message: v })}
          placeholder={t('inspector.handoffMessagePlaceholder')}
        />
      </Field>
    </>
  );
}

// ---------------------------------------------------------------------------
// Main NodeInspector panel
// ---------------------------------------------------------------------------

/**
 * NodeInspector — right sidebar shown when a node is selected on the canvas.
 *
 * Edits the selected node's data in-place via useReactFlow().setNodes.
 * Receives setEdges so AiRouterInspector can clean up orphaned edges when
 * intents are removed.
 *
 * @param {{
 *   selectedNode: import('@xyflow/react').Node | null,
 *   setEdges: Function,
 *   onClose: () => void,
 * }} props
 */
export default function NodeInspector({ selectedNode, setEdges, onClose }) {
  const { t } = useTranslation('flows');
  const { setNodes } = useReactFlow();

  const patch = useCallback(
    (changes) => {
      if (!selectedNode) return;
      setNodes((nds) =>
        nds.map((n) =>
          n.id === selectedNode.id
            ? { ...n, data: { ...n.data, ...changes } }
            : n,
        ),
      );
    },
    [selectedNode, setNodes],
  );

  if (!selectedNode) return null;

  const { type, data } = selectedNode;

  const typeLabel = t(`nodes.${type}.label`, { defaultValue: type });

  function renderBody() {
    switch (type) {
      case 'commentTrigger':
        return <CommentTriggerInspector data={data} patch={patch} />;
      case 'dmTrigger':
        return <DmTriggerInspector data={data} patch={patch} />;
      case 'condition':
        return <ConditionInspector data={data} patch={patch} />;
      case 'sendMessage':
        return <SendMessageInspector data={data} patch={patch} />;
      case 'waitForInput':
        return <WaitForInputInspector data={data} patch={patch} />;
      case 'aiRouter':
        return (
          <AiRouterInspector
            data={data}
            patch={patch}
            nodeId={selectedNode.id}
            setEdges={setEdges}
          />
        );
      case 'pause':
        return <PauseInspector data={data} patch={patch} />;
      default:
        return (
          <p className="text-[11px] text-nexus-muted italic">
            {t('inspector.unknownType')}
          </p>
        );
    }
  }

  return (
    <aside className="flex w-56 shrink-0 flex-col border-l border-nexus-border/60 bg-white/40 backdrop-blur-sm dark:border-white/10 dark:bg-slate-900/40">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-nexus-border/60 px-3 py-2 dark:border-white/10">
        <span className="text-[11px] font-semibold text-slate-700 dark:text-slate-200">
          {typeLabel}
        </span>
        <button
          type="button"
          onClick={onClose}
          className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
          aria-label={t('inspector.close')}
        >
          <X size={13} />
        </button>
      </div>

      {/* Fields */}
      <div className="flex flex-col gap-3 overflow-y-auto p-3">
        {renderBody()}
      </div>
    </aside>
  );
}
