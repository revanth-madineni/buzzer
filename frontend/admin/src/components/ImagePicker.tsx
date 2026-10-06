/**
 * Choose an uploaded image, or upload a new one (T8 spec §4.10, §4.13).
 *
 * Copied byte-for-byte into the host and admin apps (scripts/check_theme.py checks it);
 * change both together. The endpoints differ per app, so the caller passes `listImages`
 * and `uploadImage`; this file only imports what exists identically in both apps.
 */
import { useEffect, useState } from 'react';
import { AuthImage } from './AuthImage';
import { Button } from './ui/button';
import { Input } from './ui/input';

/** ImageResponse: an uploaded image's metadata (never the bytes). */
export interface ImageInfo {
  id: string;
  mime_type: string;
  width: number;
  height: number;
  byte_size: number;
  sha256: string;
  alt_text: string;
  course_id: number | null;
  created_at: string;
}

/** One question (and role) that references an image. */
export interface ImageUsage {
  game_id: number;
  game_title: string;
  course_id: number | null;
  question_id: number;
  question_number: number;
  role: 'map' | 'prompt' | 'option';
}

/** An image in a list endpoint, with where it is used. */
export interface ImageListItem extends ImageInfo {
  usage: ImageUsage[];
  /** Uses in games the caller can't access (always 0 for admins). */
  hidden_usage_count: number;
}

export const ALT_TEXT_HINT =
  "Describe what's shown. Players' phones receive this text, so don't name the answer.";
export const ALT_TEXT_MISSING = "No description — screen-reader users can't tell this image apart";
export const ALT_TEXT_MAX = 250;
export const IMAGE_ACCEPT = 'image/png,image/jpeg,image/webp';
export const FILE_INPUT_CLASS =
  'block text-sm text-fg file:mr-3 file:rounded-lg file:border-0 file:bg-surface-hover file:px-3 file:py-1.5 file:text-fg';

/** The alt-text hint, plus the non-blocking warning when the text is empty. */
export function AltTextHint({ alt }: { alt: string }) {
  return (
    <div className="mt-1 space-y-0.5 text-xs">
      <p className="text-fg-muted">{ALT_TEXT_HINT}</p>
      {!alt.trim() && <p className="text-warning-fg">{ALT_TEXT_MISSING}</p>}
    </div>
  );
}

export function ImagePicker({
  listImages,
  uploadImage,
  onPick,
  onCancel,
}: {
  listImages: () => Promise<ImageListItem[]>;
  uploadImage: (file: File, alt: string) => Promise<ImageInfo>;
  onPick: (image: ImageInfo) => void;
  onCancel: () => void;
}) {
  const [images, setImages] = useState<ImageListItem[] | null>(null);
  const [loadError, setLoadError] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [alt, setAlt] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [fileInputKey, setFileInputKey] = useState(0);

  useEffect(() => {
    let active = true;
    listImages().then(
      (list) => {
        if (active) setImages(list);
      },
      (err: unknown) => {
        if (active) setLoadError(err instanceof Error ? err.message : 'Failed to load images');
      },
    );
    return () => {
      active = false;
    };
    // Loaded once per opening; the caller remounts the picker to reload.
  }, []);

  async function handleUpload() {
    if (!file) return;
    setUploading(true);
    setUploadError('');
    try {
      const img = await uploadImage(file, alt.trim());
      setFile(null);
      setAlt('');
      setFileInputKey((k) => k + 1);
      onPick(img);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="rounded-lg border border-line bg-surface-alt p-3 space-y-3 text-sm">
      <div className="flex items-center justify-between">
        <p className="font-semibold text-fg">Choose an image</p>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>

      {loadError && <p className="text-danger-fg">{loadError}</p>}
      {images === null && !loadError && <p className="text-fg-muted">Loading images…</p>}
      {images !== null && images.length === 0 && (
        <p className="text-fg-muted">No images yet. Upload one below.</p>
      )}
      {images !== null && images.length > 0 && (
        <div className="grid grid-cols-3 gap-2 max-h-80 overflow-auto p-1">
          {images.map((img) => (
            <button
              key={img.id}
              type="button"
              onClick={() => onPick(img)}
              className="flex flex-col gap-1 rounded-lg border border-line bg-surface p-1.5 text-left hover:bg-surface-hover"
            >
              <AuthImage imageId={img.id} alt={img.alt_text} className="h-24 w-full rounded" />
              <span
                className={`text-xs line-clamp-2 ${img.alt_text ? 'text-fg' : 'text-fg-muted'}`}
              >
                {img.alt_text || 'No description'}
              </span>
            </button>
          ))}
        </div>
      )}

      <div className="border-t border-line pt-3 space-y-2">
        <p className="font-semibold text-fg">Upload a new image</p>
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
        <Button
          type="button"
          size="sm"
          disabled={!file || uploading}
          onClick={() => void handleUpload()}
        >
          {uploading ? 'Uploading…' : 'Upload and use'}
        </Button>
      </div>
    </div>
  );
}
