// Phase 32 — drag-to-reorder image carousel for ProductForm.
//
// Uses @dnd-kit/sortable for accessible keyboard + pointer DnD.
// Uploads use the HTML5 drop-target pattern from Dropzone.jsx (zero deps).
// Reorder is optimistic; on settle calls PATCH /products/:id/images/order.
//
// Phase 32.1 — supports a "staged" mode when ``productId == null``
// (i.e. the parent ProductForm is still creating). Files are buffered
// in local state with blob-URL previews; ProductForm flushes them to
// POST /products/{id}/images after the create call returns.
import { useEffect, useRef, useState } from 'react';
import { DndContext, PointerSensor, KeyboardSensor, useSensor, useSensors, closestCenter } from '@dnd-kit/core';
import { SortableContext, arrayMove, useSortable, sortableKeyboardCoordinates, horizontalListSortingStrategy } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical, ImagePlus, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { deleteProductImage, reorderProductImages, uploadProductImage } from '../../lib/products.js';

const ACCEPT = 'image/jpeg,image/png,image/webp';

// Counter used only to mint stable client-side ids for staged previews
// (crypto.randomUUID would also work, but is gated on secure contexts
// in some browsers).
let _stagedIdSeq = 0;
function nextStagedId() {
  _stagedIdSeq += 1;
  return `staged-${Date.now()}-${_stagedIdSeq}`;
}

function SortableThumb({ image, onDelete, disabled }) {
  const { t } = useTranslation('products');
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: image.id });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };
  return (
    <div
      ref={setNodeRef}
      style={style}
      className="relative h-28 w-28 shrink-0 rounded-lg border border-nexus-border bg-slate-100 dark:bg-slate-800 overflow-hidden group"
    >
      {image.image_url ? (
        <img src={image.image_url} alt="" className="h-full w-full object-cover" />
      ) : (
        <div className="h-full w-full flex items-center justify-center text-xs text-slate-400">
          {t('images.loading')}
        </div>
      )}
      <button
        type="button"
        {...attributes}
        {...listeners}
        disabled={disabled}
        className="absolute top-1 left-1 rounded bg-white/80 p-1 text-slate-700 dark:text-slate-300 opacity-0 group-hover:opacity-100 transition-opacity cursor-grab active:cursor-grabbing"
        title={t('images.dragReorder')}
      >
        <GripVertical size={14} />
      </button>
      <button
        type="button"
        onClick={() => onDelete(image.id)}
        disabled={disabled}
        className="absolute top-1 right-1 rounded bg-white/80 p-1 text-red-600 opacity-0 group-hover:opacity-100 transition-opacity"
        title={t('images.deleteImage')}
      >
        <Trash2 size={14} />
      </button>
    </div>
  );
}

export default function ImageCarouselEditor({ productId, images, onImagesChange, maxImages = 10 }) {
  const { t } = useTranslation('products');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef(null);
  const staged = !productId;

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  // Revoke any staged blob URLs on unmount to avoid memory leaks if the
  // user navigates away without submitting. We snapshot the list inside
  // the effect closure so React's strict-mode double-invoke and parent
  // re-renders don't race the revoke.
  useEffect(() => {
    return () => {
      for (const im of images) {
        if (im?._pending && typeof im.image_url === 'string' && im.image_url.startsWith('blob:')) {
          try {
            URL.revokeObjectURL(im.image_url);
          } catch {
            /* ignore */
          }
        }
      }
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleFiles(fileList) {
    setError('');
    const files = Array.from(fileList || []);
    if (!files.length) return;
    const room = maxImages - images.length;
    if (room <= 0) {
      setError(t('images.maxReached', { max: maxImages }));
      return;
    }
    setBusy(true);
    try {
      const next = [...images];
      for (const file of files.slice(0, room)) {
        if (!ACCEPT.split(',').includes(file.type)) {
          setError(t('images.skipped', { name: file.name }));
          continue;
        }
        if (staged) {
          next.push({
            id: nextStagedId(),
            image_url: URL.createObjectURL(file),
            display_order: next.length,
            content_type: file.type,
            width: null,
            height: null,
            storage_key: '',
            _pending: true,
            _file: file,
          });
        } else {
          const uploaded = await uploadProductImage(productId, file);
          next.push(uploaded);
        }
      }
      onImagesChange(next);
    } catch (err) {
      setError(err?.body || err?.message || t('images.uploadFailed'));
    } finally {
      setBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  async function handleDelete(imageId) {
    setBusy(true);
    setError('');
    try {
      const target = images.find((im) => im.id === imageId);
      if (target?._pending) {
        if (typeof target.image_url === 'string' && target.image_url.startsWith('blob:')) {
          try {
            URL.revokeObjectURL(target.image_url);
          } catch {
            /* ignore */
          }
        }
        onImagesChange(images.filter((im) => im.id !== imageId));
      } else {
        await deleteProductImage(productId, imageId);
        onImagesChange(images.filter((im) => im.id !== imageId));
      }
    } catch (err) {
      setError(err?.body || err?.message || t('images.deleteFailed'));
    } finally {
      setBusy(false);
    }
  }

  async function handleDragEnd(event) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = images.findIndex((im) => im.id === active.id);
    const newIndex = images.findIndex((im) => im.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;
    const next = arrayMove(images, oldIndex, newIndex);
    onImagesChange(next);
    // While staged, ordering is implicit in the array; the persistence
    // call only fires after the product exists.
    if (staged) return;
    try {
      await reorderProductImages(productId, next.map((im) => im.id));
    } catch (err) {
      setError(err?.body || err?.message || t('images.reorderFailed'));
      onImagesChange(images);
    }
  }

  function onDrop(e) {
    e.preventDefault();
    setDragOver(false);
    handleFiles(e.dataTransfer.files);
  }

  return (
    <div className="space-y-3">
      <label className="block text-sm font-medium">
        {t('images.label', { count: images.length, max: maxImages })}
      </label>

      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <SortableContext items={images.map((im) => im.id)} strategy={horizontalListSortingStrategy}>
          <div className="flex flex-wrap gap-3 items-start">
            {images.map((im) => (
              <SortableThumb key={im.id} image={im} onDelete={handleDelete} disabled={busy} />
            ))}

            <label
              onDragEnter={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              className={[
                'h-28 w-28 rounded-lg border-2 border-dashed flex flex-col items-center justify-center cursor-pointer text-xs text-slate-500 dark:text-slate-400',
                dragOver ? 'border-nexus-accent bg-nexus-accent/5' : 'border-nexus-border hover:border-nexus-accent',
                images.length >= maxImages ? 'opacity-50 pointer-events-none' : '',
              ].join(' ')}
            >
              <ImagePlus size={18} />
              <span className="mt-1">{t('images.add')}</span>
              <input
                ref={fileInputRef}
                type="file"
                accept={ACCEPT}
                multiple
                className="hidden"
                onChange={(e) => handleFiles(e.target.files)}
                disabled={busy || images.length >= maxImages}
              />
            </label>
          </div>
        </SortableContext>
      </DndContext>

      {busy && <p className="text-xs text-slate-500 dark:text-slate-400">{t('images.working')}</p>}
      {error && (
        <div className="text-xs rounded border border-red-200 bg-red-50 text-red-700 px-2 py-1">
          {String(error)}
        </div>
      )}
    </div>
  );
}
