// Phase 32 — thin product API wrapper. Owner-gated server-side.
// Currency rendering helper kept here so every view picks the same.
import { api } from './api.js';

export function listProducts({ search = '', activeOnly = true, page = 1, limit = 50 } = {}) {
  const params = new URLSearchParams();
  if (search) params.set('search', search);
  params.set('active_only', String(activeOnly));
  params.set('page', String(page));
  params.set('limit', String(limit));
  return api.get(`/products?${params.toString()}`);
}

export function getProduct(id) {
  return api.get(`/products/${id}`);
}

export function createProduct(body) {
  return api.post('/products', body);
}

export function updateProduct(id, body) {
  return api.patch(`/products/${id}`, body);
}

export function deleteProduct(id) {
  return api.del(`/products/${id}`);
}

export function uploadProductImage(id, file) {
  const fd = new FormData();
  fd.append('file', file);
  return api.upload(`/products/${id}/images`, fd);
}

export function reorderProductImages(id, orderedIds) {
  return api.patch(`/products/${id}/images/order`, { ordered_ids: orderedIds });
}

export function deleteProductImage(productId, imageId) {
  return api.del(`/products/${productId}/images/${imageId}`);
}

export function formatPrice(cents, currency = 'USD') {
  const value = (Number(cents) || 0) / 100;
  try {
    return new Intl.NumberFormat(navigator.language, {
      style: 'currency',
      currency,
    }).format(value);
  } catch {
    return `${currency} ${value.toFixed(2)}`;
  }
}
