// Phase 32 — Owner-gated single-product editor.
// Route `/products/new` for creates; `/products/:id` for edits.
import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import PageHeader from '../components/layout/PageHeader.jsx';
import ProductForm from '../components/products/ProductForm.jsx';
import { deleteProduct, getProduct } from '../lib/products.js';

export default function ProductEditPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const isNew = !id || id === 'new';

  const [product, setProduct] = useState(null);
  const [loading, setLoading] = useState(!isNew);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    if (isNew) return;
    setLoading(true);
    setError('');
    try {
      const data = await getProduct(id);
      setProduct(data);
    } catch (err) {
      setError(err?.body || err?.message || 'Failed to load product.');
    } finally {
      setLoading(false);
    }
  }, [id, isNew]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleDelete(productId) {
    const ok = window.confirm('Delete this product? This cannot be undone.');
    if (!ok) return;
    try {
      await deleteProduct(productId);
      navigate('/products');
    } catch (err) {
      setError(err?.body || err?.message || 'Delete failed.');
    }
  }

  function handleSaved(saved) {
    setProduct(saved);
    if (isNew) navigate(`/products/${saved.id}`, { replace: true });
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title={isNew ? 'New product' : product?.name || 'Product'}
        right={
          <button
            type="button"
            onClick={() => navigate('/products')}
            className="inline-flex items-center gap-1 text-sm text-slate-600 hover:text-nexus-accent"
          >
            <ArrowLeft size={14} /> Back
          </button>
        }
      />

      {error && (
        <div className="rounded border border-red-200 bg-red-50 text-red-700 px-3 py-2 text-sm">
          {String(error)}
        </div>
      )}

      {loading ? (
        <div className="h-96 rounded-lg border border-nexus-border bg-slate-50 animate-pulse" />
      ) : (
        <div className="rounded-lg border border-nexus-border bg-white p-6">
          <ProductForm
            product={isNew ? null : product}
            onSaved={handleSaved}
            onDelete={handleDelete}
          />
        </div>
      )}
    </div>
  );
}
