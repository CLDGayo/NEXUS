// Phase 32 — Etsy-style product editor.
//
// Submits to POST /products (new) or PATCH /products/:id (edit). Inline
// error/success per the existing SettingsWorkspacesPage pattern.
//
// Phase 32.1 — image upload is no longer gated behind "save once". The
// carousel runs in "staged" mode when no product exists yet (previews
// via URL.createObjectURL); on create-submit we POST the product, then
// drain the staged files through POST /products/{id}/images.
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { createProduct, updateProduct, uploadProductImage } from '../../lib/products.js';
import ImageCarouselEditor from './ImageCarouselEditor.jsx';

const CURRENCY_OPTIONS = ['USD', 'EUR', 'GBP', 'JPY', 'PHP', 'CAD', 'AUD'];

function dollarsToCents(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n < 0) return 0;
  return Math.round(n * 100);
}

function centsToDollars(cents) {
  const n = Number(cents) || 0;
  return (n / 100).toFixed(2);
}

export default function ProductForm({ product, onSaved, onDelete }) {
  const { t } = useTranslation('products');
  const isEditing = Boolean(product?.id);
  const [name, setName] = useState(product?.name || '');
  const [description, setDescription] = useState(product?.description || '');
  const [priceDollars, setPriceDollars] = useState(centsToDollars(product?.price_cents));
  const [currency, setCurrency] = useState(product?.currency || 'USD');
  const [quantity, setQuantity] = useState(product?.quantity ?? 0);
  const [isActive, setIsActive] = useState(product?.is_active ?? true);
  const [url, setUrl] = useState(product?.url || '');
  const [images, setImages] = useState(product?.images || []);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(null);

  useEffect(() => {
    setImages(product?.images || []);
  }, [product?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleSubmit(e) {
    e.preventDefault();
    setStatus(null);
    setBusy(true);
    try {
      const body = {
        name: name.trim(),
        description: description.trim(),
        price_cents: dollarsToCents(priceDollars),
        currency: (currency || 'USD').toUpperCase(),
        quantity: Number(quantity) || 0,
        is_active: Boolean(isActive),
        url: url.trim() || null,
      };

      if (isEditing) {
        const saved = await updateProduct(product.id, body);
        setStatus({ kind: 'ok', message: t('form.saved') });
        onSaved?.(saved);
        return;
      }

      // New-product flow: create first, then drain any client-side
      // staged image previews to /products/{id}/images.
      const saved = await createProduct(body);
      const stagedFiles = images.filter((im) => im?._pending && im?._file);

      const uploaded = [];
      let uploadFailure = null;
      for (const im of stagedFiles) {
        try {
          const result = await uploadProductImage(saved.id, im._file);
          uploaded.push(result);
        } catch (err) {
          uploadFailure = err;
          break;
        } finally {
          if (typeof im.image_url === 'string' && im.image_url.startsWith('blob:')) {
            try {
              URL.revokeObjectURL(im.image_url);
            } catch {
              /* ignore */
            }
          }
        }
      }

      // Hand the merged product (server images + freshly uploaded ones)
      // back to the parent so it can route to /products/:id.
      const finalProduct = {
        ...saved,
        images: [...(saved.images || []), ...uploaded],
      };
      setImages(finalProduct.images);

      if (uploadFailure) {
        const detail = uploadFailure?.body || uploadFailure?.message || t('form.imageUploadFailed');
        setStatus({
          kind: 'err',
          message: t('form.createdImageFailed', { detail }),
        });
      } else {
        setStatus({ kind: 'ok', message: t('form.created') });
      }
      onSaved?.(finalProduct);
    } catch (err) {
      const detail = err?.body || err?.message || t('form.saveFailed');
      setStatus({ kind: 'err', message: String(detail) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div>
        <label className="block text-sm font-medium">{t('form.name')}</label>
        <input
          required
          maxLength={200}
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="mt-1 w-full rounded-md border border-nexus-border px-3 py-2 text-sm focus:border-nexus-accent focus:ring-nexus-accent"
        />
      </div>

      <div>
        <label className="block text-sm font-medium">{t('form.description')}</label>
        <textarea
          rows={6}
          maxLength={10_000}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          className="mt-1 w-full rounded-md border border-nexus-border px-3 py-2 text-sm font-mono focus:border-nexus-accent focus:ring-nexus-accent"
          placeholder={t('form.descriptionPlaceholder')}
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div>
          <label className="block text-sm font-medium">{t('form.price')}</label>
          <input
            type="number"
            inputMode="decimal"
            min="0"
            step="0.01"
            value={priceDollars}
            onChange={(e) => setPriceDollars(e.target.value)}
            className="mt-1 w-full rounded-md border border-nexus-border px-3 py-2 text-sm focus:border-nexus-accent focus:ring-nexus-accent"
          />
        </div>
        <div>
          <label className="block text-sm font-medium">{t('form.currency')}</label>
          <select
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            className="mt-1 w-full rounded-md border border-nexus-border px-3 py-2 text-sm focus:border-nexus-accent focus:ring-nexus-accent"
          >
            {CURRENCY_OPTIONS.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium">{t('form.quantity')}</label>
          <input
            type="number"
            inputMode="numeric"
            min="0"
            step="1"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            className="mt-1 w-full rounded-md border border-nexus-border px-3 py-2 text-sm focus:border-nexus-accent focus:ring-nexus-accent"
          />
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium">{t('form.url')}</label>
        <input
          type="url"
          placeholder={t('form.urlPlaceholder')}
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          className="mt-1 w-full rounded-md border border-nexus-border px-3 py-2 text-sm focus:border-nexus-accent focus:ring-nexus-accent"
        />
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          {t('form.urlHint')}
        </p>
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={isActive}
          onChange={(e) => setIsActive(e.target.checked)}
        />
        {t('form.active')}
      </label>

      <ImageCarouselEditor
        productId={isEditing ? product.id : null}
        images={images}
        onImagesChange={setImages}
      />
      {!isEditing && images.length === 0 && (
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {t('form.stagedHint')}
        </p>
      )}

      {status && (
        <div
          className={[
            'rounded border px-3 py-2 text-sm',
            status.kind === 'ok'
              ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
              : 'border-red-200 bg-red-50 text-red-700',
          ].join(' ')}
        >
          {status.message}
        </div>
      )}

      <div className="flex items-center justify-between gap-3 pt-2">
        <button
          type="submit"
          disabled={busy || !name.trim()}
          className="rounded-md bg-nexus-accent px-4 py-2 text-sm font-medium text-white shadow-sm hover:opacity-95 disabled:opacity-50"
        >
          {busy ? t('form.saving') : isEditing ? t('form.saveChanges') : t('form.createProduct')}
        </button>
        {isEditing && onDelete && (
          <button
            type="button"
            onClick={() => onDelete(product.id)}
            className="text-sm text-red-600 hover:text-red-700"
          >
            {t('form.deleteProduct')}
          </button>
        )}
      </div>
    </form>
  );
}
