import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { List, Lock, Pencil, Plus, Trash2 } from 'lucide-react';
import { api } from '../../lib/api';
import { Button } from '../../components/ui/button';
import { Card, CardContent, CardHeader } from '../../components/ui/card';
import { Input } from '../../components/ui/input';

interface HostGame {
  id: number;
  title: string;
  description: string;
  max_players: number;
  course_id: number | null;
  restricted: boolean;
  created_at: string;
  question_count: number;
}

interface GameFields {
  title: string;
  description: string;
  maxPlayers: string;
}

const emptyFields: GameFields = { title: '', description: '', maxPlayers: '150' };

function GameForm({
  heading,
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  heading: string;
  initial: GameFields;
  submitLabel: string;
  onSubmit: (f: GameFields) => Promise<void>;
  onCancel: () => void;
}) {
  const [fields, setFields] = useState(initial);
  const [saving, setSaving] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await onSubmit(fields);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card className="mb-6">
      <CardHeader><h3 className="text-lg font-semibold text-fg">{heading}</h3></CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-3">
          <Input
            placeholder="Title"
            value={fields.title}
            onChange={(e) => setFields({ ...fields, title: e.target.value })}
            required
          />
          <textarea
            placeholder="Description (optional)"
            value={fields.description}
            onChange={(e) => setFields({ ...fields, description: e.target.value })}
            className="w-full rounded-lg border border-line-strong bg-surface-alt px-3 py-2 text-fg resize-none"
            rows={3}
          />
          <div>
            <label className="block text-xs text-fg-muted mb-1">Max players</label>
            <Input
              type="number"
              value={fields.maxPlayers}
              onChange={(e) => setFields({ ...fields, maxPlayers: e.target.value })}
              min="1"
              max="500"
            />
          </div>
          <div className="flex gap-3">
            <Button type="submit" disabled={saving}>{saving ? 'Saving…' : submitLabel}</Button>
            <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

export default function GamesPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const navigate = useNavigate();
  const [games, setGames] = useState<HostGame[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<HostGame | null>(null);

  async function load() {
    try {
      setGames(await api.get<HostGame[]>(`/host/courses/${courseId}/games`));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load games');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    setError('');
    setCreating(false);
    setEditing(null);
    void load();
  }, [courseId]);

  function body(f: GameFields) {
    return { title: f.title, description: f.description, max_players: Number(f.maxPlayers) };
  }

  async function create(f: GameFields) {
    setError('');
    try {
      await api.post(`/host/courses/${courseId}/games`, body(f));
      setCreating(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create game');
    }
  }

  async function update(f: GameFields) {
    if (!editing) return;
    setError('');
    try {
      await api.put(`/host/games/${editing.id}`, body(f));
      setEditing(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update game');
    }
  }

  async function remove(g: HostGame) {
    if (!confirm(`Delete "${g.title}" and its questions? This cannot be undone.`)) return;
    setError('');
    try {
      await api.delete(`/host/games/${g.id}`);
      setGames((prev) => prev.filter((x) => x.id !== g.id));
    } catch (err) {
      // e.g. GAME_HAS_RESULTS or GAME_LIVE — the server's message says which.
      setError(err instanceof Error ? err.message : 'Failed to delete game');
    }
  }

  return (
    <div className="p-8 max-w-4xl">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold text-fg">Games</h2>
        <Button size="sm" onClick={() => { setCreating(true); setEditing(null); }}>
          <Plus size={16} className="mr-1" /> New Game
        </Button>
      </div>

      {error && <p className="text-danger-fg mb-4 text-sm">{error}</p>}

      {creating && (
        <GameForm
          heading="Create Game"
          initial={emptyFields}
          submitLabel="Create"
          onSubmit={create}
          onCancel={() => setCreating(false)}
        />
      )}
      {editing && (
        <GameForm
          key={editing.id}
          heading="Edit Game"
          initial={{
            title: editing.title,
            description: editing.description,
            maxPlayers: String(editing.max_players),
          }}
          submitLabel="Save"
          onSubmit={update}
          onCancel={() => setEditing(null)}
        />
      )}

      {loading ? (
        <p className="text-fg-muted">Loading…</p>
      ) : games.length === 0 ? (
        <p className="text-fg-muted">No games in this course yet.</p>
      ) : (
        <div className="space-y-3">
          {games.map((g) => (
            <Card key={g.id} className="flex items-center justify-between px-6 py-4">
              <div>
                <p className="font-semibold text-fg flex items-center gap-2">
                  {g.title}
                  {g.restricted && (
                    <span
                      className="inline-flex items-center gap-1 rounded bg-warning-soft px-1.5 py-0.5 text-xs font-semibold text-warning-fg"
                      title="Only hosts an admin granted can use this game"
                    >
                      <Lock size={11} /> Restricted
                    </span>
                  )}
                </p>
                {g.description && <p className="text-fg-muted text-sm mt-0.5 line-clamp-1">{g.description}</p>}
                <p className="text-fg-muted text-xs mt-0.5">
                  {g.question_count} question{g.question_count !== 1 ? 's' : ''} · Max {g.max_players} players
                </p>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => { setEditing(g); setCreating(false); }}>
                  <Pencil size={14} />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => navigate(`/courses/${courseId}/games/${g.id}/questions`)}
                >
                  <List size={14} className="mr-1" /> Questions
                </Button>
                <Button variant="destructive" size="sm" onClick={() => void remove(g)}>
                  <Trash2 size={14} />
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
