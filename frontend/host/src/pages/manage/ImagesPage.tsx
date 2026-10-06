import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Upload, Trash2, Pencil, RefreshCw, X } from 'lucide-react';
import { api } from '../../lib/api';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Card } from '../../components/ui/card';
import { AuthImage } from '../../components/AuthImage';
import {
  ALT_TEXT_MAX,
  ALT_TEXT_MISSING,
  AltTextHint,
  FILE_INPUT_CLASS,
  IMAGE_ACCEPT,
  type ImageInfo,
  type ImageListItem,
  type ImageUsage,
} from '../../components/ImagePicker';

const imagePath = (id: string) => `/host/images/${encodeURIComponent(id)}`;

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function usageLabel(u: ImageUsage): string {
  return `${u.game_title} — Q${u.question_number} (${u.role})`;
}

/** The question editor of the game that uses the image, under that game's own course. */
function usageLink(u: ImageUsage, fallbackCourseId: string | undefined): string {
  return `/courses/${u.course_id ?? fallbackCourseId}/games/${u.game_id}/questions`;
}

/** "This will update N question(s) in M game(s)…" counts: distinct questions and games. */
function replaceCounts(img: ImageListItem): { questions: number; games: number } {
  return {
    questions: new Set(img.usage.map((u) => u.question_id)).size,
    games: new Set(img.usage.map((u) => u.game_id)).size,
  };
}

function ImageCard({
  img,
  courseId,
  onView,
  onChanged,
  onDeleteFailed,
}: {
  img: ImageListItem;
  courseId: string | undefined;
  onView: () => void;
  onChanged: () => Promise<void>;
  onDeleteFailed: (message: string) => Promise<void>;
}) {
  const [editingAlt, setEditingAlt] = useState(false);
  const [alt, setAlt] = useState(img.alt_text);
  const [replaceFile, setReplaceFile] = useState<File | null>(null);
  const [replaceAlt, setReplaceAlt] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  const inUse = img.usage.length > 0 || img.hidden_usage_count > 0;
  const counts = replaceCounts(img);

  async function saveAlt() {
    setBusy(true);
    setError('');
    try {
      await api.patch<ImageInfo>(imagePath(img.id), { alt_text: alt.trim() });
      setEditingAlt(false);
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save alt text');
    } finally {
      setBusy(false);
    }
  }

  async function replace() {
    if (!replaceFile) return;
    setBusy(true);
    setError('');
    try {
      const form = new FormData();
      form.append('file', replaceFile);
      if (replaceAlt.trim()) form.append('alt_text', replaceAlt.trim());
      await api.postForm<ImageInfo>(`${imagePath(img.id)}/replace`, form);
      setReplaceFile(null);
      setReplaceAlt('');
      await onChanged();
    } catch (err) {
      // GAME_LIVE / IMAGE_ASPECT_MISMATCH / CONFLICT: the server's message says why.
      setError(err instanceof Error ? err.message : 'Replace failed');
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!confirm('Delete this image? This cannot be undone.')) return;
    setBusy(true);
    setError('');
    try {
      await api.delete(imagePath(img.id));
      await onChanged();
    } catch (err) {
      // A 409 IMAGE_IN_USE means it was put to use since the list loaded: reload and say so.
      await onDeleteFailed(err instanceof Error ? err.message : 'Delete failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="p-4">
      <div className="flex gap-4">
        <button
          type="button"
          onClick={onView}
          title="View full size"
          className="shrink-0 rounded-lg border border-line hover:bg-surface-hover p-1"
        >
          <AuthImage imageId={img.id} alt={img.alt_text} className="h-24 w-32 rounded" />
        </button>

        <div className="flex-1 min-w-0 space-y-2 text-sm">
          <div className="flex flex-wrap items-center gap-2 text-xs text-fg-muted">
            <span>
              {img.width} × {img.height} px · {formatSize(img.byte_size)} · uploaded{' '}
              {new Date(img.created_at).toLocaleDateString()}
            </span>
          </div>

          {editingAlt ? (
            <div>
              <div className="flex gap-2">
                <Input
                  value={alt}
                  maxLength={ALT_TEXT_MAX}
                  onChange={(e) => setAlt(e.target.value)}
                  className="text-sm"
                />
                <Button size="sm" disabled={busy} onClick={() => void saveAlt()}>
                  Save
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setAlt(img.alt_text);
                    setEditingAlt(false);
                  }}
                >
                  Cancel
                </Button>
              </div>
              <AltTextHint alt={alt} />
            </div>
          ) : (
            <div className="flex items-start gap-2">
              {img.alt_text ? (
                <p className="text-fg">{img.alt_text}</p>
              ) : (
                <p className="text-warning-fg text-xs">{ALT_TEXT_MISSING}</p>
              )}
              <button
                type="button"
                onClick={() => {
                  setAlt(img.alt_text);
                  setEditingAlt(true);
                }}
                title="Edit alt text"
                className="shrink-0 text-fg-muted hover:text-fg"
              >
                <Pencil size={14} />
              </button>
            </div>
          )}

          <div>
            <p className="text-xs font-semibold text-fg-muted">Used by</p>
            {!inUse ? (
              <p className="text-xs text-fg-muted">Not used by any question</p>
            ) : (
              <ul className="text-xs space-y-0.5">
                {img.usage.map((u) => (
                  <li key={`${u.question_id}:${u.role}`}>
                    <Link to={usageLink(u, courseId)} className="text-accent-fg hover:underline">
                      {usageLabel(u)}
                    </Link>
                  </li>
                ))}
                {img.hidden_usage_count > 0 && (
                  <li className="text-fg-muted">
                    + {img.hidden_usage_count} in games you can't access
                  </li>
                )}
              </ul>
            )}
          </div>

          {replaceFile && (
            <div className="rounded-lg border border-line bg-surface-alt p-3 space-y-2">
              <p className="text-fg">
                This will update {counts.questions} question(s) in {counts.games} game(s) to use
                the new image. Past session reports will show the new image too.
              </p>
              <p className="text-xs text-fg-muted">New file: {replaceFile.name}</p>
              <div>
                <label className="block text-xs text-fg-muted mb-1">
                  New alt text (leave empty to keep the current one)
                </label>
                <Input
                  value={replaceAlt}
                  maxLength={ALT_TEXT_MAX}
                  onChange={(e) => setReplaceAlt(e.target.value)}
                  className="text-sm"
                />
                <AltTextHint alt={replaceAlt || img.alt_text} />
              </div>
              <div className="flex gap-2">
                <Button size="sm" disabled={busy} onClick={() => void replace()}>
                  {busy ? 'Replacing…' : 'Replace everywhere'}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setReplaceFile(null);
                    setReplaceAlt('');
                  }}
                >
                  Cancel
                </Button>
              </div>
            </div>
          )}

          {error && <p className="text-danger-fg text-xs">{error}</p>}
        </div>

        <div className="flex flex-col gap-1 shrink-0">
          <input
            ref={fileRef}
            type="file"
            accept={IMAGE_ACCEPT}
            className="hidden"
            onChange={(e) => {
              setReplaceFile(e.target.files?.[0] ?? null);
              e.target.value = '';
            }}
          />
          <Button size="sm" variant="outline" disabled={busy} onClick={() => fileRef.current?.click()}>
            <RefreshCw size={14} className="mr-1" /> Replace
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={busy || inUse}
            title={inUse ? 'In use: remove it from every question first' : 'Delete image'}
            onClick={() => void remove()}
          >
            {inUse ? (
              'In use'
            ) : (
              <>
                <Trash2 size={14} className="mr-1" /> Delete
              </>
            )}
          </Button>
        </div>
      </div>
    </Card>
  );
}

/** Full-size view over a scrim; click anywhere or press Escape to close. */
function ImageOverlay({ img, onClose }: { img: ImageListItem; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-scrim/80 p-8"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Image, full size"
    >
      <button
        type="button"
        onClick={onClose}
        className="absolute top-4 right-4 rounded-lg p-2 text-on-scrim"
        aria-label="Close"
      >
        <X size={24} />
      </button>
      <AuthImage imageId={img.id} alt={img.alt_text} className="max-h-[90vh] max-w-[90vw]" />
    </div>
  );
}

export default function ImagesPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const [images, setImages] = useState<ImageListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [viewing, setViewing] = useState<ImageListItem | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [alt, setAlt] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [fileInputKey, setFileInputKey] = useState(0);

  async function load() {
    try {
      setImages(await api.get<ImageListItem[]>(`/host/courses/${courseId}/images`));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load images');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    setError('');
    void load();
  }, [courseId]);

  async function handleUpload() {
    if (!file) return;
    setUploading(true);
    setUploadError('');
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('alt_text', alt.trim());
      await api.postForm<ImageInfo>(`/host/courses/${courseId}/images`, form);
      setFile(null);
      setAlt('');
      setFileInputKey((k) => k + 1);
      await load();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="p-8 max-w-4xl">
      <h2 className="text-2xl font-bold text-fg mb-1">Images</h2>
      <p className="text-fg-muted text-sm mb-6">
        Images in this course, and the questions that use them.
      </p>

      {error && <p className="text-danger-fg mb-4 text-sm">{error}</p>}

      <Card className="p-4 mb-6 space-y-3 text-sm">
        <h3 className="font-semibold text-fg">
          <Upload size={14} className="inline mr-1" /> Upload an image
        </h3>
        <div>
          <label className="block text-xs text-fg-muted mb-1">
            File (PNG, JPEG or WebP, up to 2 MB)
          </label>
          <input
            key={fileInputKey}
            type="file"
            accept={IMAGE_ACCEPT}
            disabled={uploading}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className={FILE_INPUT_CLASS}
          />
        </div>
        <div>
          <label className="block text-xs text-fg-muted mb-1">Alt text</label>
          <Input
            value={alt}
            maxLength={ALT_TEXT_MAX}
            onChange={(e) => setAlt(e.target.value)}
            className="text-sm"
          />
          <AltTextHint alt={alt} />
        </div>
        {uploadError && <p className="text-danger-fg text-xs">{uploadError}</p>}
        <Button size="sm" disabled={!file || uploading} onClick={() => void handleUpload()}>
          {uploading ? 'Uploading…' : 'Upload'}
        </Button>
      </Card>

      {loading ? (
        <p className="text-fg-muted">Loading…</p>
      ) : images.length === 0 ? (
        <p className="text-fg-muted">No images here yet.</p>
      ) : (
        <div className="space-y-3">
          {images.map((img) => (
            <ImageCard
              key={img.id}
              img={img}
              courseId={courseId}
              onView={() => setViewing(img)}
              onChanged={load}
              onDeleteFailed={async (message) => {
                await load();
                setError(message);
              }}
            />
          ))}
        </div>
      )}

      {viewing && <ImageOverlay img={viewing} onClose={() => setViewing(null)} />}
    </div>
  );
}
