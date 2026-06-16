import { Sparkles, Rocket } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { ACTIVE_CAPABILITIES, ROADMAP_FEATURES } from '../lib/whatsNew.js';
import CapabilityCard from '../components/whatsnew/CapabilityCard.jsx';
import RoadmapCard from '../components/whatsnew/RoadmapCard.jsx';
import { usePageMountTimeline } from '../hooks/usePageMountTimeline.js';

// Curated platform showcase — distinct from the chronological release
// feed at /changelog. Section A markets shipped capabilities; Section B
// previews the locked premium roadmap.
export default function WhatsNewPage() {
  const { t } = useTranslation('whatsnew');
  const pageRef = usePageMountTimeline();
  return (
    <div ref={pageRef} className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl space-y-8 p-6">
        <header data-animate>
          <h2 className="flex items-center gap-2 text-lg font-bold tracking-tight text-slate-900 dark:text-slate-100">
            <Sparkles size={18} className="text-nexus-accent" />
            {t('title')}
          </h2>
          <p className="mt-1 text-sm text-nexus-muted">
            {t('subtitle')}
          </p>
        </header>

        <section className="space-y-3">
          <div>
            <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
              {t('activeTitle')}
            </h3>
            <p className="text-xs text-nexus-muted">
              {t('activeSubtitle')}
            </p>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {ACTIVE_CAPABILITIES.map((item) => (
              <div key={item.key} data-animate>
                <CapabilityCard item={item} />
              </div>
            ))}
          </div>
        </section>

        <section className="space-y-3">
          <div className="flex items-center gap-2">
            <Rocket size={15} className="text-slate-400" />
            <div>
              <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                {t('roadmapTitle')}
              </h3>
              <p className="text-xs text-nexus-muted">
                {t('roadmapSubtitle')}
              </p>
            </div>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {ROADMAP_FEATURES.map((item) => (
              <div key={item.key} data-animate>
                <RoadmapCard item={item} />
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
