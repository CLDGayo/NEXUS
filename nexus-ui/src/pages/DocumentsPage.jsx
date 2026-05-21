import { useState } from 'react';
import SummaryCards from '../components/documents/SummaryCards.jsx';
import Dropzone from '../components/documents/Dropzone.jsx';
import DocumentsTable from '../components/documents/DocumentsTable.jsx';

export default function DocumentsPage() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [summary, setSummary] = useState({ totalNotes: 0, totalChunks: 0, chunksAvailable: false });
  const [lastSync, setLastSync] = useState(Date.now());

  function handleLoaded(next) {
    setSummary(next);
    setLastSync(Date.now());
  }

  function handleUploaded() {
    setRefreshKey((k) => k + 1);
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-4 p-6">
        <SummaryCards
          totalNotes={summary.totalNotes}
          totalChunks={summary.totalChunks}
          chunksAvailable={summary.chunksAvailable}
          lastSync={lastSync}
        />
        <Dropzone onUploaded={handleUploaded} />
        <DocumentsTable refreshKey={refreshKey} onLoaded={handleLoaded} />
      </div>
    </div>
  );
}
