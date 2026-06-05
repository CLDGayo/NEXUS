// Phase 32 — Owner-gated product list view.
//
// Phase 32.1 — page no longer renders its own PageHeader; AppShell
// owns the top bar for every route. The "New" CTA moved into the
// toolbar row so it stays a one-click action.
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Plus, Search } from 'lucide-react';
import { useTenant } from '../hooks/useTenant.js';
import ProductsTable from '../components/products/ProductsTable.jsx';
import { deleteProduct, listProducts } from '../lib/products.js';

export default function ProductsDashboardPage() {
  const { cacheVersion } = useTenant();
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [activeOnly, setActiveOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const fetchPage = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await listProducts({ search, activeOnly, page: 1, limit: 100 });
      setItems(res.items || []);
      setTotal(res.total || 0);
    } catch (err) {
      setError(err?.body || err?.message || 'Failed to load.');
    } finally {
      setLoading(false);
    }
  }, [search, activeOnly]);

  useEffect(() => {
    fetchPage();
  }, [fetchPage, cacheVersion]);

  async function handleDelete(product) {
    const ok = window.confirm(`Delete "${product.name}"? This cannot be undone.`);
    if (!ok) return;
    try {
      await deleteProduct(product.id);
      setItems((curr) => curr.filter((p) => p.id !== product.id));
      setTotal((n) => Math.max(0, n - 1));
    } catch (err) {
      setError(err?.body || err?.message || 'Delete failed.');
    }
  }

  return (
    <div className="space-y-5 p-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name or description…"
            className="w-full rounded-md border border-nexus-border bg-white dark:bg-slate-900 pl-9 pr-3 py-2 text-sm focus:border-nexus-accent focus:ring-nexus-accent"
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
          <input
            type="checkbox"
            checked={activeOnly}
            onChange={(e) => setActiveOnly(e.target.checked)}
          />
          Active only
        </label>
        <div className="text-sm text-slate-500 dark:text-slate-400">
          {total} product{total === 1 ? '' : 's'}
        </div>
        <Link
          to="/products/new"
          className="inline-flex items-center gap-2 rounded-md bg-nexus-accent px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:opacity-95"
        >
          <Plus size={14} />
          New
        </Link>
      </div>

      {error && (
        <div className="rounded border border-red-200 bg-red-50 text-red-700 px-3 py-2 text-sm">
          {String(error)}
        </div>
      )}

      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-64 rounded-lg border border-nexus-border bg-slate-50 dark:bg-slate-900 animate-pulse" />
          ))}
        </div>
      ) : (
        <ProductsTable products={items} onDelete={handleDelete} />
      )}
    </div>
  );
}
