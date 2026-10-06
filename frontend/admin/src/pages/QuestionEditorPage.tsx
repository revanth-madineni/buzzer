import { useCallback, useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Plus, Trash2, ChevronUp, ChevronDown, Download } from 'lucide-react';
import { api } from '../lib/api';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Card, CardContent, CardHeader } from '../components/ui/card';
import { MapCanvas } from '../components/MapCanvas';
import { AuthImage } from '../components/AuthImage';
import {
  ALT_TEXT_MISSING,
  FILE_INPUT_CLASS,
  IMAGE_ACCEPT,
  ImagePicker,
  type ImageInfo,
  type ImageListItem,
} from '../components/ImagePicker';
import { drawTarget, type DrawRect, type Point } from '../lib/mapPin';

type QuestionType = 'multiple_choice' | 'true_false' | 'fill_in_the_blank' | 'multi_select' | 'map_pin';
type GradingType = 'ACCURACY' | 'COMPLETENESS';

interface Question {
  id: number;
  type: QuestionType;
  grading_type: GradingType;
  prompt: string;
  config: Record<string, unknown>;
  answer_data: Record<string, unknown>;
  time_limit_seconds: number;
  points_value: number;
  order_index: number;
  /** {imageId: alt_text} for every image the question references (T8). */
  image_alt?: Record<string, string>;
}

interface Game { id: number; title: string; course_id?: number | null }

type UploadImage = (file: File, alt: string) => Promise<ImageInfo>;
type ListImages = () => Promise<ImageListItem[]>;

// ---- helpers for building config/answer_data per type ----

/** An option is text or an image (T8): with `imageId` set, `text` is kept but not sent. */
interface McOption { text: string; points: number; imageId: string | null }

/** config.options + config.optionImageIds (omitted when no option has an image). */
function optionsConfig(options: McOption[]): Record<string, unknown> {
  const config: Record<string, unknown> = {
    options: options.map((o) => (o.imageId ? '' : o.text)),
  };
  if (options.some((o) => o.imageId)) config.optionImageIds = options.map((o) => o.imageId);
  return config;
}

/** Why options with images can't be saved, or null. No check without option images. */
function optionImagesFormError(options: McOption[]): string | null {
  if (!options.some((o) => o.imageId)) return null;
  const i = options.findIndex((o) => !o.imageId && !o.text.trim());
  return i === -1 ? null : `Option ${i + 1} needs text or an image.`;
}

function buildMcPayload(options: McOption[], _grading: GradingType) {
  return {
    config: optionsConfig(options),
    answer_data: { answer_points: options.map((o) => o.points) },
  };
}

function buildTfPayload(truePoints: number, falsePoints: number) {
  return {
    config: {},
    answer_data: { answer_points: { true: truePoints, false: falsePoints } },
  };
}

function buildMsPayload(options: McOption[]) {
  return {
    config: optionsConfig(options),
    answer_data: { answer_points: options.map((o) => o.points) },
  };
}

interface FibAnswer { text: string; points: number }

function buildFibPayload(answers: FibAnswer[], editDistance: number) {
  return {
    config: {},
    answer_data: {
      acceptedAnswers: answers.map((a) => a.text),
      answerPoints: answers.map((a) => a.points),
      editDistance,
    },
  };
}

// ---- QuestionForm subcomponent ----

interface FormState {
  type: QuestionType;
  grading: GradingType;
  prompt: string;
  /** Prompt image (T8), any type; shown on the projector. */
  promptImageId: string | null;
  /** Alt text of the images in this form, for display only (never sent). */
  imageAlt: Record<string, string>;
  timeLimitSeconds: number;
  pointsValue: number;
  // multiple_choice
  mcOptions: McOption[];
  // true_false
  tfTruePoints: number;
  tfFalsePoints: number;
  // fill_in_the_blank
  fibAnswers: FibAnswer[];
  fibEditDistance: number;
  // multi_select
  msOptions: McOption[];
  // map_pin (T7): target as image fractions, radii in image-width units
  imageId: string | null;
  imageWidth: number | null;
  imageHeight: number | null;
  targetX: number | null;
  targetY: number | null;
  fullRadius: number;
  zeroRadius: number;
}

// Server limits (backend schemas/admin.py). The editor defaults are higher than the floor.
const MAP_PIN_MIN_FULL_RADIUS = 0.02;
const MAP_PIN_MAX_ZERO_RADIUS = 2;
const MAP_PIN_EASY_FULL_RADIUS = 0.04;
const MAP_PIN_SLIDER_MAX = 0.5;

/** Why a map_pin form can't be saved (same rules for both grading types), or null. */
function mapPinFormError(form: FormState): string | null {
  if (!form.imageId) return 'Upload an image for this map pin question.';
  if (form.targetX === null || form.targetY === null) return 'Click the image to set the target.';
  if (!(form.fullRadius >= MAP_PIN_MIN_FULL_RADIUS))
    return `Full-credit radius must be at least ${MAP_PIN_MIN_FULL_RADIUS}.`;
  if (!(form.zeroRadius > form.fullRadius))
    return 'Zero-credit radius must be larger than the full-credit radius.';
  if (!(form.zeroRadius <= MAP_PIN_MAX_ZERO_RADIUS))
    return `Zero-credit radius must be at most ${MAP_PIN_MAX_ZERO_RADIUS}.`;
  return null;
}

const defaultForm = (): FormState => ({
  type: 'multiple_choice',
  grading: 'ACCURACY',
  prompt: '',
  promptImageId: null,
  imageAlt: {},
  timeLimitSeconds: 30,
  pointsValue: 1,
  mcOptions: [{ text: '', points: 1, imageId: null }, { text: '', points: 0, imageId: null }],
  tfTruePoints: 1,
  tfFalsePoints: 0,
  fibAnswers: [{ text: '', points: 1 }],
  fibEditDistance: 0,
  msOptions: [{ text: '', points: 1, imageId: null }, { text: '', points: 1, imageId: null }],
  imageId: null,
  imageWidth: null,
  imageHeight: null,
  targetX: null,
  targetY: null,
  fullRadius: 0.04,
  zeroRadius: 0.15,
});

function questionToForm(q: Question): FormState {
  const base: FormState = {
    ...defaultForm(),
    type: q.type,
    grading: q.grading_type,
    prompt: q.prompt,
    promptImageId: (q.config['promptImageId'] as string | undefined) ?? null,
    imageAlt: { ...(q.image_alt ?? {}) },
    timeLimitSeconds: q.time_limit_seconds,
    pointsValue: q.points_value,
  };
  const optionImageIds = (q.config['optionImageIds'] as (string | null)[] | undefined) ?? [];
  if (q.type === 'multiple_choice') {
    const opts = (q.config['options'] as string[]) ?? [];
    const pts = (q.answer_data['answer_points'] as number[]) ?? [];
    base.mcOptions = opts.map((text, i) => ({
      text,
      points: pts[i] ?? 0,
      imageId: optionImageIds[i] ?? null,
    }));
  } else if (q.type === 'true_false') {
    const ap = q.answer_data['answer_points'] as { true: number; false: number } | undefined;
    base.tfTruePoints = ap?.true ?? 1;
    base.tfFalsePoints = ap?.false ?? 0;
  } else if (q.type === 'fill_in_the_blank') {
    const accepted = (q.answer_data['acceptedAnswers'] as string[]) ?? [];
    const pts = (q.answer_data['answerPoints'] as number[]) ?? [];
    base.fibAnswers = accepted.length
      ? accepted.map((text, i) => ({ text, points: pts[i] ?? 1 }))
      : [{ text: '', points: 1 }];
    base.fibEditDistance = (q.answer_data['editDistance'] as number) ?? 0;
  } else if (q.type === 'multi_select') {
    const opts = (q.config['options'] as string[]) ?? [];
    const pts = (q.answer_data['answer_points'] as number[]) ?? [];
    base.msOptions = opts.length
      ? opts.map((text, i) => ({ text, points: pts[i] ?? 1, imageId: optionImageIds[i] ?? null }))
      : defaultForm().msOptions;
  } else if (q.type === 'map_pin') {
    const cfg = q.config as { imageId?: string; imageWidth?: number; imageHeight?: number };
    const ad = q.answer_data as {
      targets?: { x: number; y: number }[];
      fullRadius?: number;
      zeroRadius?: number;
    };
    base.imageId = cfg.imageId ?? null;
    base.imageWidth = cfg.imageWidth ?? null;
    base.imageHeight = cfg.imageHeight ?? null;
    base.targetX = ad.targets?.[0]?.x ?? null;
    base.targetY = ad.targets?.[0]?.y ?? null;
    // Kept exactly as stored, even above the slider's range (e.g. from an import).
    base.fullRadius = ad.fullRadius ?? base.fullRadius;
    base.zeroRadius = ad.zeroRadius ?? base.zeroRadius;
  }
  return base;
}

function formToPayload(form: FormState) {
  let config: Record<string, unknown> = {};
  let answer_data: Record<string, unknown> = {};
  if (form.type === 'multiple_choice') {
    const p = buildMcPayload(form.mcOptions, form.grading);
    config = p.config;
    answer_data = p.answer_data;
  } else if (form.type === 'true_false') {
    const p = buildTfPayload(form.tfTruePoints, form.tfFalsePoints);
    config = p.config;
    answer_data = p.answer_data;
  } else if (form.type === 'multi_select') {
    // Blank options are dropped; an option with an image isn't blank (T8).
    const p = buildMsPayload(form.msOptions.filter((o) => o.imageId || o.text.trim()));
    config = p.config;
    answer_data = p.answer_data;
  } else if (form.type === 'map_pin') {
    // Same answer_data for both grading types: both show the same reveal. The server
    // fills in imageWidth/imageHeight from the stored image.
    config = { imageId: form.imageId };
    answer_data = {
      targets: [{ x: form.targetX, y: form.targetY }],
      fullRadius: form.fullRadius,
      zeroRadius: form.zeroRadius,
    };
  } else {
    const p = buildFibPayload(form.fibAnswers.filter((a) => a.text.trim()), form.fibEditDistance);
    config = p.config;
    answer_data = p.answer_data;
  }
  if (form.promptImageId) config = { ...config, promptImageId: form.promptImageId };
  const points_value =
    form.grading === 'COMPLETENESS' || form.type === 'map_pin'
      ? form.pointsValue
      : form.type === 'multiple_choice'
      ? Math.max(0, ...form.mcOptions.map((o) => o.points))
      : form.type === 'true_false'
      ? Math.max(form.tfTruePoints, form.tfFalsePoints)
      : form.type === 'multi_select'
      ? form.msOptions.reduce((sum, o) => sum + (o.points > 0 ? o.points : 0), 0)
      : Math.max(0, ...form.fibAnswers.map((a) => a.points));
  return {
    type: form.type,
    grading_type: form.grading,
    prompt: form.prompt,
    config,
    answer_data,
    time_limit_seconds: form.timeLimitSeconds,
    points_value,
  };
}

/** A radius: number input (source of truth, full server range) + slider (0.02–0.5). */
function RadiusInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex-1">
      <label className="block text-xs text-fg-muted mb-1">{label}</label>
      <div className="flex items-center gap-2">
        <input
          type="range"
          min={MAP_PIN_MIN_FULL_RADIUS}
          max={MAP_PIN_SLIDER_MAX}
          step={0.005}
          value={Math.min(value, MAP_PIN_SLIDER_MAX)}
          onChange={(e) => onChange(Number(e.target.value))}
          className="flex-1"
        />
        <Input
          type="number"
          min={MAP_PIN_MIN_FULL_RADIUS}
          max={MAP_PIN_MAX_ZERO_RADIUS}
          step={0.005}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-24 text-sm"
        />
      </div>
    </div>
  );
}

type SetField = <K extends keyof FormState>(key: K, value: FormState[K]) => void;

/** Thumbnail + alt text (or the empty-alt warning) of an image in the form. */
function ImagePreview({ imageId, alt, size }: { imageId: string; alt: string; size: 'sm' | 'md' }) {
  return (
    <div className="flex items-center gap-2 min-w-0">
      <AuthImage
        imageId={imageId}
        alt={alt}
        className={`${size === 'sm' ? 'h-10 w-14' : 'h-20 w-28'} shrink-0 rounded`}
      />
      {alt ? (
        <span className="text-xs text-fg truncate">{alt}</span>
      ) : (
        <span className="text-xs text-warning-fg">{ALT_TEXT_MISSING}</span>
      )}
    </div>
  );
}

/** Prompt image (T8): any question type, shown on the projector under the prompt. */
function PromptImageField({
  form,
  set,
  listImages,
  uploadImage,
}: {
  form: FormState;
  set: SetField;
  listImages: ListImages;
  uploadImage: UploadImage;
}) {
  const [picking, setPicking] = useState(false);
  return (
    <div className="space-y-2">
      <label className="block text-xs text-fg-muted">Prompt image (shown on the projector)</label>
      {form.promptImageId ? (
        <div className="flex items-center gap-2">
          <div className="flex-1 min-w-0">
            <ImagePreview
              imageId={form.promptImageId}
              alt={form.imageAlt[form.promptImageId] ?? ''}
              size="md"
            />
          </div>
          <Button type="button" variant="outline" size="sm" onClick={() => setPicking(true)}>
            Change
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => set('promptImageId', null)}>
            Remove
          </Button>
        </div>
      ) : (
        <Button type="button" variant="outline" size="sm" onClick={() => setPicking(true)}>
          <Plus size={12} className="mr-1" /> Add image
        </Button>
      )}
      {picking && (
        <ImagePicker
          listImages={listImages}
          uploadImage={uploadImage}
          onPick={(img) => {
            set('imageAlt', { ...form.imageAlt, [img.id]: img.alt_text });
            set('promptImageId', img.id);
            setPicking(false);
          }}
          onCancel={() => setPicking(false)}
        />
      )}
    </div>
  );
}

/**
 * Options of a multiple choice or multi-select question. Each option is text or an image
 * (T8); the image lives on the option object, so adding or deleting options keeps it with
 * its option.
 */
function OptionList({
  form,
  set,
  field,
  pointsLabel,
  minPoints,
  newPoints,
  listImages,
  uploadImage,
}: {
  form: FormState;
  set: SetField;
  field: 'mcOptions' | 'msOptions';
  pointsLabel: string;
  minPoints?: string;
  newPoints: number;
  listImages: ListImages;
  uploadImage: UploadImage;
}) {
  const [pickingFor, setPickingFor] = useState<number | null>(null);
  const options = form[field];

  function update(i: number, patch: Partial<McOption>) {
    const opts = [...options];
    opts[i] = { ...opts[i], ...patch };
    set(field, opts);
  }

  return (
    <>
      {form.grading === 'ACCURACY' && (
        <div className="flex gap-2 mb-1 px-0.5">
          <span className="flex-1 text-xs text-fg-muted">Answer text or image</span>
          <span className="w-24 text-xs text-fg-muted">{pointsLabel}</span>
          <span className="w-20" />
          {options.length > 2 && <span className="w-7" />}
        </div>
      )}
      <div className="space-y-2">
        {options.map((opt, i) => (
          <div key={i} className="space-y-2">
            <div className="flex gap-2 items-center">
              {opt.imageId ? (
                <div className="flex-1 min-w-0 flex items-center gap-2">
                  <div className="flex-1 min-w-0">
                    <ImagePreview
                      imageId={opt.imageId}
                      alt={form.imageAlt[opt.imageId] ?? ''}
                      size="sm"
                    />
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="shrink-0"
                    onClick={() => update(i, { imageId: null })}
                  >
                    Remove image
                  </Button>
                </div>
              ) : (
                <Input
                  placeholder={`Option ${i + 1}`}
                  value={opt.text}
                  onChange={(e) => update(i, { text: e.target.value })}
                  className="flex-1 text-sm"
                />
              )}
              {form.grading === 'ACCURACY' && (
                <Input
                  type="number"
                  placeholder="pts"
                  value={opt.points}
                  onChange={(e) => update(i, { points: Number(e.target.value) })}
                  className="w-24 text-sm"
                  min={minPoints}
                  step="any"
                />
              )}
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="w-20 shrink-0"
                onClick={() => setPickingFor(pickingFor === i ? null : i)}
              >
                Image
              </Button>
              {options.length > 2 && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setPickingFor(null);
                    set(field, options.filter((_, j) => j !== i));
                  }}
                >
                  <Trash2 size={12} />
                </Button>
              )}
            </div>
            {pickingFor === i && (
              <ImagePicker
                listImages={listImages}
                uploadImage={uploadImage}
                onPick={(img) => {
                  set('imageAlt', { ...form.imageAlt, [img.id]: img.alt_text });
                  update(i, { imageId: img.id });
                  setPickingFor(null);
                }}
                onCancel={() => setPickingFor(null)}
              />
            )}
          </div>
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => set(field, [...options, { text: '', points: newPoints, imageId: null }])}
        >
          <Plus size={12} className="mr-1" /> Add option
        </Button>
      </div>
    </>
  );
}

function MapPinFields({
  form,
  set,
  listImages,
  uploadImage,
}: {
  form: FormState;
  set: SetField;
  listImages: ListImages;
  uploadImage: UploadImage;
}) {
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [picking, setPicking] = useState(false);

  function applyImage(img: ImageInfo) {
    set('imageAlt', { ...form.imageAlt, [img.id]: img.alt_text });
    set('imageId', img.id);
    set('imageWidth', img.width);
    set('imageHeight', img.height);
  }

  async function handleFile(file: File | undefined) {
    if (!file) return;
    setUploading(true);
    setUploadError('');
    try {
      // "Replace image" = upload a new one; the old image row is left as it is.
      const img = await uploadImage(file, '');
      applyImage(img);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setUploading(false);
    }
  }

  const target: Point | null =
    form.targetX !== null && form.targetY !== null ? { x: form.targetX, y: form.targetY } : null;
  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, fit: DrawRect) => {
      if (target) drawTarget(ctx, fit, target, form.fullRadius, form.zeroRadius);
    },
    // target is derived from targetX/targetY
    [form.targetX, form.targetY, form.fullRadius, form.zeroRadius],
  );

  return (
    <div className="space-y-3">
      <div>
        <label className="block text-xs text-fg-muted mb-1">
          {form.imageId ? 'Replace image' : 'Upload image'} (PNG, JPEG or WebP, up to 2 MB)
        </label>
        <div className="flex flex-wrap items-center gap-3">
          <input
            type="file"
            accept={IMAGE_ACCEPT}
            disabled={uploading}
            onChange={(e) => {
              void handleFile(e.target.files?.[0]);
              e.target.value = '';
            }}
            className={FILE_INPUT_CLASS}
          />
          <Button type="button" variant="outline" size="sm" onClick={() => setPicking(true)}>
            Choose from images
          </Button>
        </div>
        {uploading && <p className="text-fg-muted text-xs mt-1">Uploading…</p>}
        {uploadError && <p className="text-danger-fg text-xs mt-1">{uploadError}</p>}
        {picking && (
          <div className="mt-2">
            <ImagePicker
              listImages={listImages}
              uploadImage={uploadImage}
              onPick={(img) => {
                applyImage(img);
                setPicking(false);
              }}
              onCancel={() => setPicking(false)}
            />
          </div>
        )}
      </div>

      {form.imageId && form.imageWidth && form.imageHeight && (
        <div>
          <p className="text-xs text-fg-muted mb-1">
            {target
              ? `Target (${target.x.toFixed(3)}, ${target.y.toFixed(3)}) — click or drag to move it`
              : 'Click the image to set the target'}
          </p>
          <MapCanvas
            imageId={form.imageId}
            imageWidth={form.imageWidth}
            imageHeight={form.imageHeight}
            heightCap={0.7}
            draw={draw}
            onPoint={(p) => {
              set('targetX', p.x);
              set('targetY', p.y);
            }}
          />
        </div>
      )}

      <div className="flex gap-4">
        <RadiusInput
          label="Full-credit radius (fraction of image width)"
          value={form.fullRadius}
          onChange={(v) => set('fullRadius', v)}
        />
        <RadiusInput
          label="Zero-credit radius"
          value={form.zeroRadius}
          onChange={(v) => set('zeroRadius', v)}
        />
      </div>
      {form.fullRadius < MAP_PIN_EASY_FULL_RADIUS && form.fullRadius >= MAP_PIN_MIN_FULL_RADIUS && (
        <p className="text-warning-fg text-xs">
          A full-credit radius below {MAP_PIN_EASY_FULL_RADIUS} may be hard to hit on a phone.
        </p>
      )}
      <p className="text-fg-muted text-xs">
        Full points inside the solid circle, falling linearly to zero at the dashed circle.
        {form.grading === 'COMPLETENESS' &&
          ' Completeness: any tap gets full points; the target and circles are still shown at reveal.'}
      </p>
    </div>
  );
}

function QuestionForm({
  initial,
  onSave,
  onCancel,
  saving,
  listImages,
  uploadImage,
}: {
  initial: FormState;
  onSave: (payload: ReturnType<typeof formToPayload>) => void;
  onCancel: () => void;
  saving: boolean;
  listImages: ListImages;
  uploadImage: UploadImage;
}) {
  const [form, setForm] = useState<FormState>(initial);
  const [formError, setFormError] = useState('');

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  return (
    <div className="space-y-4">
      {/* Type + grading */}
      <div className="flex gap-3">
        <div className="flex-1">
          <label className="block text-xs text-fg-muted mb-1">Question type</label>
          <select
            className="w-full rounded-lg border border-line-strong bg-surface-alt px-3 py-2 text-fg text-sm"
            value={form.type}
            onChange={(e) => set('type', e.target.value as QuestionType)}
          >
            <option value="multiple_choice">Multiple Choice</option>
            <option value="true_false">True / False</option>
            <option value="fill_in_the_blank">Fill in the Blank</option>
            <option value="multi_select">Multi-Select (Select All That Apply)</option>
            <option value="map_pin">Map pin (tap on image)</option>
          </select>
        </div>
        <div className="flex-1">
          <label className="block text-xs text-fg-muted mb-1">Grading</label>
          <select
            className="w-full rounded-lg border border-line-strong bg-surface-alt px-3 py-2 text-fg text-sm"
            value={form.grading}
            onChange={(e) => set('grading', e.target.value as GradingType)}
          >
            <option value="ACCURACY">Accuracy</option>
            <option value="COMPLETENESS">Completeness</option>
          </select>
        </div>
      </div>

      {/* Prompt */}
      <div>
        <label className="block text-xs text-fg-muted mb-1">Prompt</label>
        <textarea
          className="w-full rounded-lg border border-line-strong bg-surface-alt px-3 py-2 text-fg resize-none text-sm"
          rows={3}
          placeholder="Question text\u2026"
          value={form.prompt}
          onChange={(e) => set('prompt', e.target.value)}
          required
        />
      </div>

      <PromptImageField form={form} set={set} listImages={listImages} uploadImage={uploadImage} />

      {/* Type-specific */}
      {form.type === 'multiple_choice' && (
        <div>
          <label className="block text-xs text-fg-muted mb-2">Options</label>
          <OptionList
            form={form}
            set={set}
            field="mcOptions"
            pointsLabel="Points"
            minPoints="0"
            newPoints={0}
            listImages={listImages}
            uploadImage={uploadImage}
          />
        </div>
      )}

      {form.type === 'multi_select' && (
        <div>
          <label className="block text-xs text-fg-muted mb-2">Options</label>
          <OptionList
            form={form}
            set={set}
            field="msOptions"
            pointsLabel="Points (neg = penalty)"
            newPoints={1}
            listImages={listImages}
            uploadImage={uploadImage}
          />
          {form.grading === 'ACCURACY' && (
            <p className="text-fg-muted text-xs mt-1">
              Correct options: positive pts. Distractors: negative pts (penalty). Score = sum of selected, capped at 0.
            </p>
          )}
        </div>
      )}

      {form.type === 'true_false' && form.grading === 'ACCURACY' && (
        <div>
          <label className="block text-xs text-fg-muted mb-2">Points per answer</label>
          <div className="flex gap-4">
            <div>
              <span className="text-fg text-sm">True:</span>
              <Input
                type="number"
                value={form.tfTruePoints}
                onChange={(e) => set('tfTruePoints', Number(e.target.value))}
                className="w-28 mt-1 text-sm"
                min="0"
                step="any"
              />
            </div>
            <div>
              <span className="text-fg text-sm">False:</span>
              <Input
                type="number"
                value={form.tfFalsePoints}
                onChange={(e) => set('tfFalsePoints', Number(e.target.value))}
                className="w-28 mt-1 text-sm"
                min="0"
                step="any"
              />
            </div>
          </div>
        </div>
      )}

      {form.type === 'fill_in_the_blank' && form.grading === 'ACCURACY' && (
        <div className="space-y-3">
          <div>
            <label className="block text-xs text-fg-muted mb-2">Accepted answers</label>
            <div className="flex gap-2 mb-1 px-0.5">
              <span className="flex-1 text-xs text-fg-muted">Answer text</span>
              <span className="w-24 text-xs text-fg-muted">Points</span>
              {form.fibAnswers.length > 1 && <span className="w-7" />}
            </div>
            <div className="space-y-2">
              {form.fibAnswers.map((ans, i) => (
                <div key={i} className="flex gap-2 items-center">
                  <Input
                    placeholder={`Answer ${i + 1}`}
                    value={ans.text}
                    onChange={(e) => {
                      const answers = [...form.fibAnswers];
                      answers[i] = { ...answers[i], text: e.target.value };
                      set('fibAnswers', answers);
                    }}
                    className="flex-1 text-sm"
                  />
                  <Input
                    type="number"
                    placeholder="pts"
                    value={ans.points}
                    onChange={(e) => {
                      const answers = [...form.fibAnswers];
                      answers[i] = { ...answers[i], points: Number(e.target.value) };
                      set('fibAnswers', answers);
                    }}
                    className="w-24 text-sm"
                    min="0"
                    step="any"
                  />
                  {form.fibAnswers.length > 1 && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => set('fibAnswers', form.fibAnswers.filter((_, j) => j !== i))}
                    >
                      <Trash2 size={12} />
                    </Button>
                  )}
                </div>
              ))}
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => set('fibAnswers', [...form.fibAnswers, { text: '', points: 1 }])}
              >
                <Plus size={12} className="mr-1" /> Add answer
              </Button>
            </div>
          </div>
          <div>
            <label className="block text-xs text-fg-muted mb-1">Edit distance tolerance (fuzzy match)</label>
            <Input
              type="number"
              value={form.fibEditDistance}
              onChange={(e) => set('fibEditDistance', Number(e.target.value))}
              className="w-28 text-sm"
              min="0"
            />
          </div>
        </div>
      )}

      {form.type === 'map_pin' && (
        <MapPinFields form={form} set={set} listImages={listImages} uploadImage={uploadImage} />
      )}

      {/* Time + points */}
      <div className="flex gap-4">
        <div>
          <label className="block text-xs text-fg-muted mb-1">Time limit (seconds)</label>
          <Input
            type="number"
            value={form.timeLimitSeconds}
            onChange={(e) => set('timeLimitSeconds', Number(e.target.value))}
            className="w-28 text-sm"
            min="2"
            max="300"
          />
        </div>
        {(form.grading === 'COMPLETENESS' || form.type === 'map_pin') && (
          <div>
            <label className="block text-xs text-fg-muted mb-1">Points value</label>
            <Input
              type="number"
              value={form.pointsValue}
              onChange={(e) => set('pointsValue', Number(e.target.value))}
              className="w-28 text-sm"
              min="0"
              max="100000"
              step="any"
            />
          </div>
        )}
      </div>

      {formError && <p className="text-danger-fg text-sm">{formError}</p>}
      <div className="flex gap-3">
        <Button
          type="button"
          onClick={() => {
            const blocked =
              form.type === 'map_pin'
                ? mapPinFormError(form)
                : form.type === 'multiple_choice'
                ? optionImagesFormError(form.mcOptions)
                : form.type === 'multi_select'
                ? optionImagesFormError(form.msOptions)
                : null;
            setFormError(blocked ?? '');
            if (!blocked) onSave(formToPayload(form));
          }}
          disabled={saving}
        >
          {saving ? 'Saving\u2026' : 'Save Question'}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  );
}

/** List line: "Map pin — target (0.42, 0.37), r 0.04 → 0.15". */
function mapPinSummary(q: Question): string {
  const ad = q.answer_data as {
    targets?: { x: number; y: number }[];
    fullRadius?: number;
    zeroRadius?: number;
  };
  const t = ad.targets?.[0];
  const target = t ? `(${t.x.toFixed(2)}, ${t.y.toFixed(2)})` : '(not set)';
  return `Map pin — target ${target}, r ${ad.fullRadius ?? '?'} → ${ad.zeroRadius ?? '?'}`;
}

/** Number of options that are images (T8). */
function optionImageCount(q: Question): number {
  const ids = (q.config['optionImageIds'] as (string | null)[] | undefined) ?? [];
  return ids.filter(Boolean).length;
}

/** An option in the list: its text, or a thumbnail when it is an image (T8). */
function OptionLabel({
  q,
  index,
  text,
  className,
}: {
  q: Question;
  index: number;
  text: string;
  className: string;
}) {
  const imageId = ((q.config['optionImageIds'] as (string | null)[] | undefined) ?? [])[index];
  if (!imageId) return <span className={className}>{text}</span>;
  const alt = q.image_alt?.[imageId] ?? '';
  return (
    <span className="flex items-center gap-2">
      <AuthImage imageId={imageId} alt={alt} className="h-8 w-12 rounded" />
      <span className={className}>{alt}</span>
    </span>
  );
}

// ---- Main page ----

export default function QuestionEditorPage() {
  const { gameId } = useParams<{ gameId: string }>();
  const navigate = useNavigate();
  const [game, setGame] = useState<Game | null>(null);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showAddForm, setShowAddForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [downloading, setDownloading] = useState(false);

  async function load() {
    try {
      const [g, qs] = await Promise.all([
        api.get<Game>(`/admin/games/${gameId}`),
        api.get<Question[]>(`/admin/games/${gameId}/questions`),
      ]);
      setGame(g);
      setQuestions(qs);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [gameId]);

  /** The picker lists the game's course's images, or the unassigned ones for a courseless game. */
  function listImages(): Promise<ImageListItem[]> {
    return api.get<ImageListItem[]>(
      game?.course_id != null ? `/admin/images?course_id=${game.course_id}` : '/admin/images?unassigned=true',
    );
  }

  /** Admin uploads go to /admin/images, tagged with the game's course if it has one. */
  async function uploadImage(file: File, alt: string): Promise<ImageInfo> {
    const form = new FormData();
    form.append('file', file);
    form.append('alt_text', alt);
    if (game?.course_id != null) form.append('course_id', String(game.course_id));
    return api.postForm<ImageInfo>('/admin/images', form);
  }

  async function addQuestion(payload: ReturnType<typeof formToPayload>) {
    setSaving(true);
    setError('');
    try {
      await api.post(`/admin/games/${gameId}/questions`, payload);
      setShowAddForm(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save question');
    } finally {
      setSaving(false);
    }
  }

  async function updateQuestion(id: number, payload: ReturnType<typeof formToPayload>) {
    setSaving(true);
    setError('');
    try {
      await api.put(`/admin/games/${gameId}/questions/${id}`, payload);
      setEditingId(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update question');
    } finally {
      setSaving(false);
    }
  }

  async function deleteQuestion(id: number) {
    if (!confirm('Delete this question?')) return;
    try {
      await api.delete(`/admin/games/${gameId}/questions/${id}`);
      setQuestions((prev) => prev.filter((q) => q.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete question');
    }
  }

  async function moveQuestion(index: number, direction: -1 | 1) {
    const newOrder = [...questions];
    const target = index + direction;
    if (target < 0 || target >= newOrder.length) return;
    [newOrder[index], newOrder[target]] = [newOrder[target], newOrder[index]];
    try {
      await api.post(`/admin/games/${gameId}/questions/reorder`, {
        order: newOrder.map((q) => q.id),
      });
      setQuestions(newOrder);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reorder');
    }
  }

  async function handleExport() {
    setDownloading(true);
    setError('');
    try {
      await api.download(`/admin/games/${gameId}/export`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed');
    } finally {
      setDownloading(false);
    }
  }

  const typeLabel: Record<QuestionType, string> = {
    multiple_choice: 'MC',
    true_false: 'T/F',
    fill_in_the_blank: 'Fill',
    multi_select: 'Multi',
    map_pin: 'Map',
  };

  if (loading) return <div className="p-8 text-fg-muted">Loading\u2026</div>;

  return (
    <div className="p-8 max-w-4xl space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <button
            onClick={() => navigate('/games')}
            className="flex items-center gap-2 text-fg-muted hover:text-fg text-sm mb-2"
          >
            <ArrowLeft size={14} /> Back to Games
          </button>
          <h2 className="text-2xl font-bold text-fg">{game?.title}</h2>
          <p className="text-fg-muted text-sm mt-0.5">{questions.length} question{questions.length !== 1 ? 's' : ''}</p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void handleExport()}
            disabled={downloading}
          >
            <Download size={14} className="mr-1" />
            {downloading ? 'Exporting\u2026' : 'Export JSON'}
          </Button>
          <Button size="sm" onClick={() => { setShowAddForm(true); setEditingId(null); }}>
            <Plus size={14} className="mr-1" /> Add Question
          </Button>
        </div>
      </div>

      {error && <p className="text-danger-fg text-sm">{error}</p>}

      {/* Add question form */}
      {showAddForm && (
        <Card>
          <CardHeader><h3 className="font-semibold text-fg">New Question</h3></CardHeader>
          <CardContent>
            <QuestionForm
              initial={defaultForm()}
              onSave={(payload) => void addQuestion(payload)}
              onCancel={() => setShowAddForm(false)}
              saving={saving}
              listImages={listImages}
              uploadImage={uploadImage}
            />
          </CardContent>
        </Card>
      )}

      {/* Question list */}
      {questions.length === 0 && !showAddForm && (
        <p className="text-fg-muted">No questions yet. Add one above.</p>
      )}

      <div className="space-y-4">
        {questions.map((q, i) => (
          <Card key={q.id}>
            {editingId === q.id ? (
              <>
                <CardHeader>
                  <h3 className="font-semibold text-fg">Edit Question {i + 1}</h3>
                </CardHeader>
                <CardContent>
                  <QuestionForm
                    initial={questionToForm(q)}
                    onSave={(payload) => void updateQuestion(q.id, payload)}
                    onCancel={() => setEditingId(null)}
                    saving={saving}
                    listImages={listImages}
                    uploadImage={uploadImage}
                  />
                </CardContent>
              </>
            ) : (
              <div className="flex items-start gap-4 px-6 py-4">
                {/* Reorder buttons */}
                <div className="flex flex-col gap-1 mt-1">
                  <button
                    onClick={() => void moveQuestion(i, -1)}
                    disabled={i === 0}
                    className="text-fg-muted enabled:hover:text-fg disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <ChevronUp size={16} />
                  </button>
                  <button
                    onClick={() => void moveQuestion(i, 1)}
                    disabled={i === questions.length - 1}
                    className="text-fg-muted enabled:hover:text-fg disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <ChevronDown size={16} />
                  </button>
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-fg-muted text-xs font-mono">Q{i + 1}</span>
                    <span className="rounded px-1.5 py-0.5 text-xs font-semibold bg-surface-alt text-fg-muted">
                      {typeLabel[q.type]}
                    </span>
                    <span className="rounded px-1.5 py-0.5 text-xs font-semibold bg-surface-alt text-fg-muted">
                      {q.grading_type}
                    </span>
                    {optionImageCount(q) > 0 && (
                      <span className="rounded px-1.5 py-0.5 text-xs font-semibold bg-surface-alt text-fg-muted">
                        {optionImageCount(q)} image option{optionImageCount(q) !== 1 ? 's' : ''}
                      </span>
                    )}
                    {typeof q.config['promptImageId'] === 'string' && (
                      <span className="rounded px-1.5 py-0.5 text-xs font-semibold bg-surface-alt text-fg-muted">
                        prompt image
                      </span>
                    )}
                    <span className="text-fg-muted text-xs">{q.time_limit_seconds}s \u00b7 {q.points_value}pts</span>
                  </div>
                  <p className="text-fg text-sm leading-relaxed">{q.prompt}</p>

                  {q.type === 'multiple_choice' && (
                    <div className="mt-2 space-y-1">
                      {((q.config['options'] as string[]) ?? []).map((opt, oi) => {
                        const pts = ((q.answer_data['answer_points'] as number[]) ?? [])[oi] ?? 0;
                        return (
                          <div key={oi} className="flex items-center gap-2 text-xs">
                            <span className={pts > 0 ? 'text-success-fg' : 'text-fg-muted'}>
                              {pts > 0 ? '\u2713' : '\u25cb'}
                            </span>
                            <OptionLabel q={q} index={oi} text={opt} className={pts > 0 ? 'text-fg' : 'text-fg-muted'} />
                            {pts > 0 && <span className="text-fg-muted">({pts}pts)</span>}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {q.type === 'true_false' && (
                    <div className="mt-2 flex gap-4 text-xs">
                      {(['true', 'false'] as const).map((k) => {
                        const pts = (q.answer_data['answer_points'] as Record<string, number>)?.[k] ?? 0;
                        return (
                          <span key={k} className={pts > 0 ? 'text-success-fg' : 'text-fg-muted'}>
                            {k.charAt(0).toUpperCase() + k.slice(1)}: {pts}pts
                          </span>
                        );
                      })}
                    </div>
                  )}

                  {q.type === 'fill_in_the_blank' && (
                    <div className="mt-2 text-xs text-fg-muted">
                      Accepted: {((q.answer_data['acceptedAnswers'] as string[]) ?? []).join(', ')}
                      {(q.answer_data['editDistance'] as number) > 0 && (
                        <span className="ml-2 text-fg-muted">(\u00b1{q.answer_data['editDistance'] as number} edit distance)</span>
                      )}
                    </div>
                  )}

                  {q.type === 'map_pin' && (
                    <div className="mt-2 text-xs text-fg-muted">
                      {mapPinSummary(q)}
                    </div>
                  )}

                  {q.type === 'multi_select' && (
                    <div className="mt-2 space-y-1">
                      {((q.config['options'] as string[]) ?? []).map((opt, oi) => {
                        const pts = ((q.answer_data['answer_points'] as number[]) ?? [])[oi] ?? 0;
                        const isCorrect = pts > 0;
                        return (
                          <div key={oi} className="flex items-center gap-2 text-xs">
                            <span className={isCorrect ? 'text-success-fg' : pts < 0 ? 'text-danger-fg' : 'text-fg-muted'}>
                              {isCorrect ? '\u2713' : pts < 0 ? '\u2212' : '\u25cb'}
                            </span>
                            <OptionLabel q={q} index={oi} text={opt} className={isCorrect ? 'text-fg' : 'text-fg-muted'} />
                            {pts !== 0 && <span className="text-fg-muted">({pts > 0 ? '+' : ''}{pts}pts)</span>}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>

                <div className="flex gap-1 shrink-0">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => { setEditingId(q.id); setShowAddForm(false); }}
                  >
                    Edit
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void deleteQuestion(q.id)}
                  >
                    <Trash2 size={14} />
                  </Button>
                </div>
              </div>
            )}
          </Card>
        ))}
      </div>
    </div>
  );
}
