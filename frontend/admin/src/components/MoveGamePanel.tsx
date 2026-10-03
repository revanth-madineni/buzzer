import { useState } from 'react';
import { api } from '../lib/api';
import { Button } from './ui/button';

export interface MoveCourse { id: number; name: string; semester: string }

interface DroppedGrant {
  user_id: string;
  username: string | null;
  netid: string | null;
  display_name: string | null;
}

interface MoveResult { applied: boolean; dropped_grants: DroppedGrant[] }

function userLabel(u: DroppedGrant): string {
  return u.display_name || u.username || u.netid || u.user_id;
}

/**
 * Assign a courseless game to a course, or move it to another one, via
 * POST /admin/games/{id}/move. Always previews first (confirm=false) and lists
 * the grants that would be dropped before the admin confirms.
 */
export function MoveGamePanel({
  game,
  courses,
  fixedCourseId,
  onDone,
  onCancel,
}: {
  game: { id: number; title: string; course_id: number | null };
  courses: MoveCourse[];
  /** Target course chosen by the caller (no picker shown). */
  fixedCourseId?: number;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [target, setTarget] = useState<number | ''>(fixedCourseId ?? '');
  const [preview, setPreview] = useState<DroppedGrant[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function call(confirm: boolean) {
    if (target === '') return;
    setBusy(true);
    setError('');
    try {
      const result = await api.post<MoveResult>(`/admin/games/${game.id}/move`, {
        course_id: target,
        confirm,
      });
      if (result.applied) onDone();
      else setPreview(result.dropped_grants);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Move failed');
    } finally {
      setBusy(false);
    }
  }

  const verb = game.course_id === null ? 'Assign' : 'Move';
  const choices = courses.filter((c) => c.id !== game.course_id);

  return (
    <div className="rounded-lg border border-slate-600 bg-slate-800/50 p-3 space-y-3 text-sm">
      <p className="text-slate-200">
        {verb} <span className="font-semibold">{game.title}</span> to a course
      </p>
      {fixedCourseId === undefined && (
        <select
          value={target}
          onChange={(e) => { setTarget(e.target.value ? Number(e.target.value) : ''); setPreview(null); }}
          className="w-full rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
        >
          <option value="">Select a course…</option>
          {choices.map((c) => (
            <option key={c.id} value={c.id}>{c.name} — {c.semester}</option>
          ))}
        </select>
      )}
      {preview !== null && (
        preview.length === 0 ? (
          <p className="text-slate-300">No grants will be dropped.</p>
        ) : (
          <p className="text-amber-400">
            These users will lose access: {preview.map(userLabel).join(', ')}
          </p>
        )
      )}
      {error && <p className="text-red-400">{error}</p>}
      <div className="flex gap-2">
        {preview === null ? (
          <Button size="sm" disabled={busy || target === ''} onClick={() => void call(false)}>
            {busy ? 'Checking…' : 'Continue'}
          </Button>
        ) : (
          <Button size="sm" disabled={busy} onClick={() => void call(true)}>
            {busy ? 'Saving…' : `Confirm ${verb.toLowerCase()}`}
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  );
}
