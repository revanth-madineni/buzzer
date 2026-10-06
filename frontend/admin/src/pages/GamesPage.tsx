import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, List, Upload, Trash2, Pencil, Lock, ArrowRightLeft } from 'lucide-react';
import { api } from '../lib/api';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { MoveGamePanel, type MoveCourse } from '../components/MoveGamePanel';

interface Game {
  id: number;
  title: string;
  description: string;
  max_players: number;
  course_id: number | null;
  restricted: boolean;
  created_at: string;
}

const selectClass =
  'w-full rounded-lg border border-line-strong bg-surface-alt px-3 py-2 text-fg';

export default function GamesPage() {
  const [games, setGames] = useState<Game[]>([]);
  const [courses, setCourses] = useState<MoveCourse[]>([]);
  const [courseId, setCourseId] = useState<number | ''>('');
  const [importCourseId, setImportCourseId] = useState<number | ''>('');
  const [moving, setMoving] = useState<Game | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [maxPlayers, setMaxPlayers] = useState('150');
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);
  const [editingGame, setEditingGame] = useState<Game | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editMaxPlayers, setEditMaxPlayers] = useState('');
  const [editSaving, setEditSaving] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  async function load() {
    try {
      const [data, cs] = await Promise.all([
        api.get<Game[]>('/admin/games'),
        api.get<MoveCourse[]>('/admin/courses'),
      ]);
      setGames(data);
      setCourses(cs);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load games');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (courseId === '') return;
    setSaving(true);
    setError('');
    try {
      await api.post('/admin/games', {
        title,
        description,
        max_players: Number(maxPlayers),
        course_id: courseId,
      });
      setTitle(''); setDescription(''); setMaxPlayers('150'); setCourseId('');
      setShowForm(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create game');
    } finally {
      setSaving(false);
    }
  }

  function startEdit(g: Game) {
    setEditingGame(g);
    setEditTitle(g.title);
    setEditDescription(g.description);
    setEditMaxPlayers(String(g.max_players));
  }

  async function handleEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editingGame) return;
    setEditSaving(true);
    setError('');
    try {
      await api.put(`/admin/games/${editingGame.id}`, {
        title: editTitle,
        description: editDescription,
        max_players: Number(editMaxPlayers),
      });
      setEditingGame(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update game');
    } finally {
      setEditSaving(false);
    }
  }

  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file || importCourseId === '') return;
    setImporting(true);
    setError('');
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('course_id', String(importCourseId));
      const result = await api.postForm<{ game_id: number }>('/admin/games/import', form);
      await load();
      navigate(`/games/${result.game_id}/questions`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed');
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  }

  async function deleteGame(id: number) {
    if (!confirm('Delete this game and all its sessions? This cannot be undone.')) return;
    try {
      await api.delete(`/admin/games/${id}`);
      setGames((prev) => prev.filter((g) => g.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete game');
    }
  }

  function courseLabel(id: number): string {
    const c = courses.find((x) => x.id === id);
    return c ? `${c.name} — ${c.semester}` : `Course ${id}`;
  }

  return (
    <div className="p-8 max-w-4xl">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold text-fg">Games</h2>
        <div className="flex gap-2">
          <input ref={fileRef} type="file" accept=".json" className="hidden" onChange={handleImport} />
          <select
            value={importCourseId}
            onChange={(e) => setImportCourseId(e.target.value ? Number(e.target.value) : '')}
            className="rounded-lg border border-line-strong bg-surface px-2 py-1 text-sm text-fg"
            title="Course to import the game into"
          >
            <option value="">Import into course…</option>
            {courses.map((c) => (
              <option key={c.id} value={c.id}>{c.name} — {c.semester}</option>
            ))}
          </select>
          <Button
            variant="outline"
            size="sm"
            onClick={() => fileRef.current?.click()}
            disabled={importing || importCourseId === ''}
          >
            <Upload size={14} className="mr-1" />
            {importing ? 'Importing\u2026' : 'Import JSON'}
          </Button>
          <Button size="sm" onClick={() => setShowForm(!showForm)}>
            <Plus size={16} className="mr-1" /> New Game
          </Button>
        </div>
      </div>

      {error && <p className="text-danger-fg mb-4 text-sm">{error}</p>}

      {showForm && (
        <Card className="mb-6">
          <CardHeader><h3 className="text-lg font-semibold text-fg">Create Game</h3></CardHeader>
          <CardContent>
            <form onSubmit={handleCreate} className="space-y-3">
              <select
                value={courseId}
                onChange={(e) => setCourseId(e.target.value ? Number(e.target.value) : '')}
                className={selectClass}
                required
              >
                <option value="">Course…</option>
                {courses.map((c) => (
                  <option key={c.id} value={c.id}>{c.name} — {c.semester}</option>
                ))}
              </select>
              <Input placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} required />
              <textarea
                placeholder="Description (optional)"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="w-full rounded-lg border border-line-strong bg-surface-alt px-3 py-2 text-fg resize-none"
                rows={3}
              />
              <div>
                <label className="block text-xs text-fg-muted mb-1">Max players</label>
                <Input
                  type="number"
                  value={maxPlayers}
                  onChange={(e) => setMaxPlayers(e.target.value)}
                  min="1"
                  max="500"
                />
              </div>
              <div className="flex gap-3">
                <Button type="submit" disabled={saving}>{saving ? 'Creating\u2026' : 'Create'}</Button>
                <Button type="button" variant="ghost" onClick={() => setShowForm(false)}>Cancel</Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {editingGame && (
        <Card className="mb-6">
          <CardHeader><h3 className="text-lg font-semibold text-fg">Edit Game</h3></CardHeader>
          <CardContent>
            <form onSubmit={handleEdit} className="space-y-3">
              <Input placeholder="Title" value={editTitle} onChange={(e) => setEditTitle(e.target.value)} required />
              <textarea
                placeholder="Description (optional)"
                value={editDescription}
                onChange={(e) => setEditDescription(e.target.value)}
                className="w-full rounded-lg border border-line-strong bg-surface-alt px-3 py-2 text-fg resize-none"
                rows={3}
              />
              <div>
                <label className="block text-xs text-fg-muted mb-1">Max players</label>
                <Input
                  type="number"
                  value={editMaxPlayers}
                  onChange={(e) => setEditMaxPlayers(e.target.value)}
                  min="1"
                  max="500"
                />
              </div>
              <div className="flex gap-3">
                <Button type="submit" disabled={editSaving}>{editSaving ? 'Saving\u2026' : 'Save'}</Button>
                <Button type="button" variant="ghost" onClick={() => setEditingGame(null)}>Cancel</Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {loading ? (
        <p className="text-fg-muted">Loading\u2026</p>
      ) : games.length === 0 ? (
        <p className="text-fg-muted">No games yet.</p>
      ) : (
        <div className="space-y-3">
          {games.map((g) => (
            <Card key={g.id} className="px-6 py-4 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="font-semibold text-fg flex items-center gap-2">
                  {g.title}
                  {g.restricted && (
                    <span className="inline-flex items-center gap-1 rounded bg-warning-soft px-1.5 py-0.5 text-xs font-medium text-warning-fg">
                      <Lock size={11} /> Restricted
                    </span>
                  )}
                  {g.course_id === null && (
                    <span className="rounded bg-surface-alt px-1.5 py-0.5 text-xs font-medium text-fg-muted">
                      Unassigned
                    </span>
                  )}
                </p>
                {g.course_id !== null && (
                  <p className="text-fg-muted text-sm">{courseLabel(g.course_id)}</p>
                )}
                {g.description && <p className="text-fg-muted text-sm mt-0.5 line-clamp-1">{g.description}</p>}
                <p className="text-fg-muted text-xs mt-0.5">Max {g.max_players} players</p>
              </div>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  title="Move / assign to course"
                  onClick={() => setMoving(moving?.id === g.id ? null : g)}
                >
                  <ArrowRightLeft size={14} />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => startEdit(g)}
                >
                  <Pencil size={14} />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => navigate(`/games/${g.id}/questions`)}
                >
                  <List size={14} className="mr-1" /> Questions
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => void deleteGame(g.id)}
                >
                  <Trash2 size={14} />
                </Button>
              </div>
            </div>
            {moving?.id === g.id && (
              <MoveGamePanel
                game={g}
                courses={courses}
                onDone={() => { setMoving(null); void load(); }}
                onCancel={() => setMoving(null)}
              />
            )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
