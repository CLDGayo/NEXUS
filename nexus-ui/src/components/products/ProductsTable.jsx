// Phase 32 — grid/list of product cards on the dashboard.
import { Link } from 'react-router-dom';
import { Package, PackageX } from 'lucide-react';
import { formatPrice } from '../../lib/products.js';

function hero(images) {
  if (!images || !images.length) return null;
  return images[0].image_url || null;
}

export default function ProductsTable({ products = [], onDelete }) {
  if (!products.length) {
    return (
      <div className="rounded-lg border border-dashed border-nexus-border p-12 text-center text-sm text-slate-500">
        No products yet. Click <strong>+ New product</strong> to add your first listing.
      </div>
    );
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {products.map((p) => {
        const img = hero(p.images);
        const inStock = p.is_active && p.quantity > 0;
        return (
          <div
            key={p.id}
            className="rounded-lg border border-nexus-border bg-white overflow-hidden flex flex-col"
          >
            <Link
              to={`/products/${p.id}`}
              className="block h-40 bg-slate-100 relative"
              title="Edit product"
            >
              {img ? (
                <img src={img} alt="" className="h-full w-full object-cover" />
              ) : (
                <div className="h-full w-full flex items-center justify-center text-slate-400">
                  <Package size={32} />
                </div>
              )}
              {!inStock && (
                <span className="absolute top-2 right-2 rounded bg-red-600/90 px-2 py-0.5 text-xs font-medium text-white flex items-center gap-1">
                  <PackageX size={12} /> Out of stock
                </span>
              )}
            </Link>
            <div className="p-3 flex-1 flex flex-col gap-1">
              <Link
                to={`/products/${p.id}`}
                className="font-medium text-sm truncate hover:text-nexus-accent"
              >
                {p.name}
              </Link>
              <div className="text-sm font-semibold">
                {formatPrice(p.price_cents, p.currency)}
              </div>
              <div className="text-xs text-slate-500">
                {p.quantity} in stock · {p.images?.length || 0} image
                {(p.images?.length || 0) === 1 ? '' : 's'}
              </div>
            </div>
            <div className="px-3 py-2 border-t border-nexus-border flex items-center justify-between text-xs">
              <Link to={`/products/${p.id}`} className="text-nexus-accent hover:underline">
                Edit
              </Link>
              <button
                type="button"
                onClick={() => onDelete?.(p)}
                className="text-red-600 hover:text-red-700"
              >
                Delete
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
