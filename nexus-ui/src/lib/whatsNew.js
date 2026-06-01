// Curated showcase content for the "What's New" platform page. Copy is
// grounded in the actual shipped code (rag/orchestrator, rag/messenger)
// rather than marketing fiction — keep it accurate as features evolve.
import {
  Bot,
  MessagesSquare,
  Hand,
  Workflow,
  Building2,
  BarChart3,
  Coins,
  Palette,
} from 'lucide-react';

// Section A — capabilities live in production today.
export const ACTIVE_CAPABILITIES = [
  {
    key: 'seina-sdr',
    Icon: Bot,
    title: 'Seina AI Hybrid SDR Engine',
    summary:
      'A stateful LangGraph conversation engine that reads deep context memory across every turn and replies naturally — no robotic formatting. Each thread is persisted to Postgres so Seina always remembers what came before.',
  },
  {
    key: 'comment-triage',
    Icon: MessagesSquare,
    title: 'Stateless Public Comment Triage Engine',
    summary:
      'A high-velocity, low-latency listener that processes Facebook Page feed comments, classifies intent in a single pass, and bridges conversions securely from public replies into direct-message funnels.',
  },
  {
    key: 'hitl-guardrails',
    Icon: Hand,
    title: 'Automated Human-in-the-Loop Guardrails',
    summary:
      'Interception that instantly halts agent generation the moment a human admin engages a thread or overrides the account — then resumes automatically — so the bot never steps on your team.',
  },
  {
    key: 'crm-sync',
    Icon: Workflow,
    title: 'Omnichannel CRM Synchronization',
    summary:
      'Deep webhook synchronization with GoHighLevel that auto-enriches every conversation with live customer value, pipeline state, and transaction history.',
  },
];

// Section B — premium roadmap. Not yet built; rendered locked/blurred.
export const ROADMAP_FEATURES = [
  {
    key: 'multi-tenant',
    Icon: Building2,
    title: 'Multi-Tenant Workspace Dashboard',
    summary:
      'Let agency owners and multi-location brands connect, isolate, and manage distinct Facebook Pages and customer data sets under a single login.',
  },
  {
    key: 'conversion-analytics',
    Icon: BarChart3,
    title: 'Conversion Analytics Suite',
    summary:
      'Visual funnels showing exactly how many public comments and inbound DMs convert into a booked GoHighLevel appointment or a completed checkout.',
  },
  {
    key: 'token-metering',
    Icon: Coins,
    title: 'Usage-Based Token Metering',
    summary:
      'Per-client LLM token and API event metering, enabling tiered billing based on real conversation volume.',
  },
  {
    key: 'persona-studio',
    Icon: Palette,
    title: 'No-Code Persona Studio',
    summary:
      "A visual playground to tune your bot's tone, name, and target inventory data — without touching source code.",
  },
];
