import MessengerPanel from '../components/integrations/MessengerPanel.jsx';
import WebhookIntegrationsList from '../components/integrations/WebhookIntegrationsList.jsx';
import ApiTokensList from '../components/integrations/ApiTokensList.jsx';
import PremiumIntegrationsGrid from '../components/integrations/PremiumIntegrationsGrid.jsx';

export default function IntegrationsPage() {
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl space-y-4 p-6">
        <MessengerPanel />
        <WebhookIntegrationsList />
        <ApiTokensList />
        <PremiumIntegrationsGrid />
      </div>
    </div>
  );
}
