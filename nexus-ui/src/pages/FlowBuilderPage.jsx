import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  BackgroundVariant,
  ReactFlowProvider,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { ArrowLeft, Save, MessageCircle, Mail, GitBranch, Send, Clock, AlertCircle, CheckCircle, Brain, UserCheck, Webhook, UserCog } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useFlows } from '../hooks/useFlows.js';
import CommentTriggerNode from '../components/flows/nodes/CommentTriggerNode.jsx';
import DmTriggerNode from '../components/flows/nodes/DmTriggerNode.jsx';
import ConditionNode from '../components/flows/nodes/ConditionNode.jsx';
import SendMessageNode from '../components/flows/nodes/SendMessageNode.jsx';
import WaitForInputNode from '../components/flows/nodes/WaitForInputNode.jsx';
import AiRouterNode from '../components/flows/nodes/AiRouterNode.jsx';
import PauseNode from '../components/flows/nodes/PauseNode.jsx';
import WebhookNode from '../components/flows/nodes/WebhookNode.jsx';
import UpdateCrmNode from '../components/flows/nodes/UpdateCrmNode.jsx';
import NodeInspector from '../components/flows/NodeInspector.jsx';

/** Registry of custom node types — must be defined outside render to avoid re-registration */
const NODE_TYPES = {
  commentTrigger: CommentTriggerNode,
  dmTrigger: DmTriggerNode,
  condition: ConditionNode,
  sendMessage: SendMessageNode,
  waitForInput: WaitForInputNode,
  aiRouter: AiRouterNode,
  pause: PauseNode,
  webhook: WebhookNode,
  updateCrm: UpdateCrmNode,
};

/**
 * Count trigger nodes in a node array.
 * An active flow requires exactly one trigger node.
 * @param {import('../hooks/useFlows.js').FlowNode[]} nodes
 * @returns {number}
 */
function countTriggers(nodes) {
  return nodes.filter(
    (n) => n.type === 'commentTrigger' || n.type === 'dmTrigger',
  ).length;
}

/**
 * Generate a unique node id.
 * @param {string} type
 * @returns {string}
 */
function makeNodeId(type) {
  return `${type}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

/**
 * FlowBuilderPage — React Flow canvas for building NEXUS Flow automations.
 *
 * For an existing :id, loads the flow by finding it in the list (no single-GET endpoint).
 * For a new flow, starts with an empty canvas (the draft was already created in FlowsPage).
 * Lazy-loaded in App.jsx via React.lazy.
 */
export default function FlowBuilderPage() {
  const { t } = useTranslation('flows');
  const navigate = useNavigate();
  const { id } = useParams();

  const { flows, pages, loading: hookLoading, createFlow, updateFlow } = useFlows();

  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const reactFlowInstance = useRef(null);

  const [flowName, setFlowName] = useState('');
  const [isActive, setIsActive] = useState(false);
  const [pageId, setPageId] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState(null); // { kind: 'success'|'error', text: string }
  const [hydrated, setHydrated] = useState(false);
  const [isNew, setIsNew] = useState(false);
  const [selectedNode, setSelectedNode] = useState(null);

  // Hydrate canvas from flow_state when the flows list loads
  useEffect(() => {
    if (hookLoading || hydrated) return;

    if (id) {
      // Find flow in list — no single-GET endpoint exists
      const flow = flows.find((f) => f.id === id);
      if (!flow) {
        // List loaded but flow not found — may not exist
        if (!hookLoading) setHydrated(true);
        return;
      }
      setFlowName(flow.name || '');
      setIsActive(flow.is_active || false);
      setPageId(flow.page_id || '');
      const state = flow.flow_state || {};
      setNodes(Array.isArray(state.nodes) ? state.nodes : []);
      setEdges(Array.isArray(state.edges) ? state.edges : []);
      setHydrated(true);
    } else {
      // No id — fresh canvas (shouldn't normally happen as FlowsPage creates draft first)
      setIsNew(true);
      setFlowName(t('newFlowName'));
      if (pages.length > 0) setPageId(pages[0].facebook_page_id);
      setHydrated(true);
    }
  }, [hookLoading, flows, pages, id, hydrated, setNodes, setEdges, t]);

  const onConnect = useCallback(
    (connection) => setEdges((eds) => addEdge(connection, eds)),
    [setEdges],
  );

  const onSelectionChange = useCallback(
    ({ nodes: selected }) => {
      setSelectedNode(selected.length === 1 ? selected[0] : null);
    },
    [],
  );

  /**
   * Add a node of the given type to the canvas at a sensible default position.
   * @param {string} type
   * @param {Object} defaultData
   */
  function addNode(type, defaultData = {}) {
    const existingCount = nodes.filter((n) => n.type === type).length;
    const newNode = {
      id: makeNodeId(type),
      type,
      position: { x: 100 + existingCount * 40, y: 100 + existingCount * 60 },
      data: { ...defaultData },
    };
    setNodes((nds) => [...nds, newNode]);
  }

  /** Client-side guard: block save-as-active when canvas lacks exactly one trigger */
  const triggerCount = countTriggers(nodes);
  const activationBlocked = isActive && triggerCount !== 1;

  async function handleSave() {
    if (saving) return;
    if (activationBlocked) {
      setSaveStatus({ kind: 'error', text: t('validationOneTrigger') });
      return;
    }

    setSaving(true);
    setSaveStatus(null);

    const viewport = reactFlowInstance.current
      ? reactFlowInstance.current.getViewport()
      : null;

    const flow_state = { nodes, edges, viewport };

    try {
      if (isNew) {
        const created = await createFlow({
          page_id: pageId || (pages[0]?.facebook_page_id ?? ''),
          name: flowName || t('newFlowName'),
          flow_state,
          is_active: isActive,
        });
        setIsNew(false);
        setSaveStatus({ kind: 'success', text: t('saveSuccess') });
        // Navigate to the newly created flow's builder URL
        navigate(`/flows/${created.id}`, { replace: true });
      } else {
        await updateFlow(id, {
          name: flowName,
          flow_state,
          is_active: isActive,
        });
        setSaveStatus({ kind: 'success', text: t('saveSuccess') });
      }
    } catch (err) {
      const msg = err.body || err.message || t('saveError');
      setSaveStatus({ kind: 'error', text: msg });
    } finally {
      setSaving(false);
    }
  }

  const page = pages.find((p) => p.facebook_page_id === pageId);
  const pageName = page?.page_name || pageId || '—';

  // Node palette definition
  const palette = [
    {
      type: 'commentTrigger',
      label: t('nodes.commentTrigger.label'),
      Icon: MessageCircle,
      color: 'text-blue-500',
      defaultData: { keyword: '', matchType: 'contains', pageId, pageName },
    },
    {
      type: 'dmTrigger',
      label: t('nodes.dmTrigger.label'),
      Icon: Mail,
      color: 'text-violet-500',
      defaultData: { keyword: '' },
    },
    {
      type: 'condition',
      label: t('nodes.condition.label'),
      Icon: GitBranch,
      color: 'text-amber-500',
      defaultData: { variable: '', operator: 'contains', value: '' },
    },
    {
      type: 'sendMessage',
      label: t('nodes.sendMessage.label'),
      Icon: Send,
      color: 'text-emerald-600',
      defaultData: { message: '' },
    },
    {
      type: 'waitForInput',
      label: t('nodes.waitForInput.label'),
      Icon: Clock,
      color: 'text-orange-500',
      defaultData: { prompt: '', captureVariable: '', validation: '' },
    },
    {
      type: 'aiRouter',
      label: t('nodes.aiRouter.label'),
      Icon: Brain,
      color: 'text-violet-500',
      defaultData: {
        intents: [
          { id: 'sales', label: 'Sales' },
          { id: 'support', label: 'Support' },
        ],
        fallbackHandle: 'other',
        inputVariable: '_input',
      },
    },
    {
      type: 'pause',
      label: t('nodes.pause.label'),
      Icon: UserCheck,
      color: 'text-rose-500',
      defaultData: { durationSeconds: 86400, message: '' },
    },
    {
      type: 'webhook',
      label: t('nodes.webhook.label'),
      Icon: Webhook,
      color: 'text-sky-500',
      defaultData: { url: '', bodyTemplate: '{\n  "text": "{{ _input }}"\n}' },
    },
    {
      type: 'updateCrm',
      label: t('nodes.updateCrm.label'),
      Icon: UserCog,
      color: 'text-teal-500',
      defaultData: { action: 'add_tag', value: '', field: '' },
    },
  ];

  if (hookLoading && !hydrated) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-nexus-muted">{t('loading')}</p>
      </div>
    );
  }

  if (hydrated && id && !flows.find((f) => f.id === id)) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3">
        <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
          {t('notFound')}
        </p>
        <button
          type="button"
          onClick={() => navigate('/flows')}
          className="text-xs text-nexus-accent underline"
        >
          {t('backToFlows')}
        </button>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Builder toolbar */}
      <div className="flex shrink-0 items-center gap-3 border-b border-nexus-border/60 bg-white/60 px-4 py-2.5 backdrop-blur-sm dark:border-white/10 dark:bg-slate-900/60">
        {/* Back */}
        <button
          type="button"
          onClick={() => navigate('/flows')}
          className="glass-pressable flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50 dark:text-slate-400 dark:hover:bg-white/10"
        >
          <ArrowLeft size={13} />
          {t('back')}
        </button>

        {/* Flow name */}
        <input
          type="text"
          value={flowName}
          onChange={(e) => setFlowName(e.target.value)}
          className="flex-1 rounded-lg border border-white/60 bg-white/55 px-3 py-1.5 text-sm font-medium text-slate-800 outline-none backdrop-blur-glass focus:border-nexus-accent dark:border-white/10 dark:bg-white/5 dark:text-slate-100"
          placeholder={t('flowNamePlaceholder')}
          maxLength={255}
        />

        {/* Page chip */}
        <span className="hidden rounded-lg border border-nexus-border bg-slate-50 px-2.5 py-1.5 text-xs text-slate-600 dark:bg-white/5 dark:text-slate-400 sm:inline">
          {pageName}
        </span>

        {/* Trigger count badge */}
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
            triggerCount === 1
              ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400'
              : 'bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-400'
          }`}
        >
          {triggerCount === 1 ? t('oneTrigger') : t('triggerCount', { count: triggerCount })}
        </span>

        {/* Active toggle */}
        <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-600 dark:text-slate-400">
          <input
            type="checkbox"
            checked={isActive}
            onChange={(e) => setIsActive(e.target.checked)}
            className="accent-nexus-accent"
          />
          {t('activate')}
        </label>

        {/* Save status */}
        {saveStatus && (
          <span
            className={`flex items-center gap-1 text-xs ${
              saveStatus.kind === 'error' ? 'text-red-600' : 'text-emerald-600'
            }`}
          >
            {saveStatus.kind === 'error' ? (
              <AlertCircle size={12} />
            ) : (
              <CheckCircle size={12} />
            )}
            {saveStatus.text}
          </span>
        )}

        {/* Save button */}
        <button
          type="button"
          onClick={handleSave}
          disabled={saving || activationBlocked}
          className="inline-flex items-center gap-1.5 rounded-lg bg-nexus-accent px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          title={activationBlocked ? t('validationOneTrigger') : undefined}
        >
          <Save size={13} />
          {saving ? t('saving') : t('save')}
        </button>
      </div>

      {/* Main canvas area */}
      <ReactFlowProvider>
        <div className="flex min-h-0 flex-1">
          {/* Node palette sidebar */}
          <aside className="flex w-44 shrink-0 flex-col gap-1 border-r border-nexus-border/60 bg-white/40 p-3 backdrop-blur-sm dark:border-white/10 dark:bg-slate-900/40">
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
              {t('palette')}
            </p>
            {palette.map(({ type, label, Icon, color, defaultData }) => (
              <button
                key={type}
                type="button"
                onClick={() => addNode(type, defaultData)}
                className="glass-pressable flex items-center gap-2 rounded-lg border border-white/60 bg-white/55 px-2.5 py-2 text-left text-xs text-slate-700 hover:bg-white/80 dark:border-white/10 dark:bg-white/5 dark:text-slate-300 dark:hover:bg-white/10"
              >
                <Icon size={13} className={color} />
                {label}
              </button>
            ))}
          </aside>

          {/* React Flow canvas */}
          <div className="relative flex-1">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onSelectionChange={onSelectionChange}
              nodeTypes={NODE_TYPES}
              onInit={(instance) => { reactFlowInstance.current = instance; }}
              fitView
              fitViewOptions={{ padding: 0.2 }}
              deleteKeyCode="Delete"
              className="bg-slate-50/60 dark:bg-slate-900/60"
            >
              <Background variant={BackgroundVariant.Dots} gap={16} size={1} className="opacity-30" />
              <Controls className="!bottom-4 !left-4 !top-auto" />
              <MiniMap
                nodeColor={(n) => {
                  if (n.type === 'commentTrigger') return '#3b82f6';
                  if (n.type === 'dmTrigger') return '#8b5cf6';
                  if (n.type === 'condition') return '#f59e0b';
                  if (n.type === 'sendMessage') return '#10b981';
                  if (n.type === 'waitForInput') return '#f97316';
                  if (n.type === 'aiRouter') return '#8b5cf6';
                  if (n.type === 'pause') return '#f43f5e';
                  if (n.type === 'webhook') return '#0ea5e9';
                  if (n.type === 'updateCrm') return '#14b8a6';
                  return '#94a3b8';
                }}
                className="!bottom-4 !right-4 !top-auto rounded-lg border border-nexus-border bg-white/80 dark:bg-slate-900/80"
              />
            </ReactFlow>

            {/* Empty canvas hint */}
            {nodes.length === 0 && (
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                <p className="text-sm text-nexus-muted opacity-60">{t('canvasHint')}</p>
              </div>
            )}
          </div>

          {/* Node inspector — right sidebar, shown when a node is selected */}
          {selectedNode && (
            <NodeInspector
              selectedNode={selectedNode}
              setEdges={setEdges}
              onClose={() => setSelectedNode(null)}
            />
          )}
        </div>
      </ReactFlowProvider>
    </div>
  );
}
