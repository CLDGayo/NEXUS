import MessengerPanel from '../components/integrations/MessengerPanel.jsx';
import WebhookIntegrationsList from '../components/integrations/WebhookIntegrationsList.jsx';
import ApiTokensList from '../components/integrations/ApiTokensList.jsx';
import PremiumIntegrationsGrid from '../components/integrations/PremiumIntegrationsGrid.jsx';
import { usePageMountTimeline } from '../hooks/usePageMountTimeline.js';

export default function IntegrationsPage() {
  const pageRef = usePageMountTimeline();
  return (
    <div ref={pageRef} className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl space-y-4 p-6">
        <div data-animate>
          <MessengerPanel />
        </div>
        <div data-animate>
          <WebhookIntegrationsList />
        </div>
        <div data-animate>
          <ApiTokensList />
        </div>
        <div data-animate>
          <PremiumIntegrationsGrid />
        </div>
      </div>
    </div>
  );
}
