import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { FileText, Download } from 'lucide-react';
import { api } from '../../lib/api';
import { Button } from '../../components/ui/button';
import { Card } from '../../components/ui/card';

interface SessionItem {
  session_id: string;
  room_code: string;
  status: string;
  game_id: number;
  game_title: string;
  course_id: number;
  host_display_name: string | null;
  created_at: string;
  completed_at: string | null;
  player_count: number;
}

export default function SessionsPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError('');
    api
      .get<SessionItem[]>(`/host/courses/${courseId}/sessions?status=COMPLETED`)
      .then(setSessions)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load sessions'))
      .finally(() => setLoading(false));
  }, [courseId]);

  async function download(sessionId: string, kind: 'export' | 'report') {
    setBusy(`${sessionId}:${kind}`);
    setError('');
    try {
      await api.download(`/host/sessions/${sessionId}/${kind}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Download failed');
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="p-8 max-w-4xl">
      <h2 className="text-2xl font-bold text-fg mb-1">Completed Sessions</h2>
      <p className="text-fg-muted text-sm mb-6">Every completed game played in this course, by any host.</p>

      {error && <p className="text-danger-fg mb-4 text-sm">{error}</p>}

      {loading ? (
        <p className="text-fg-muted">Loading…</p>
      ) : sessions.length === 0 ? (
        <p className="text-fg-muted">No completed sessions yet.</p>
      ) : (
        <div className="space-y-3">
          {sessions.map((s) => (
            <Card key={s.session_id} className="flex items-center justify-between px-6 py-4">
              <div>
                <p className="font-semibold text-fg">{s.game_title}</p>
                <p className="text-fg-muted text-sm mt-0.5">
                  {new Date(s.completed_at ?? s.created_at).toLocaleString()} · {s.player_count} player
                  {s.player_count !== 1 ? 's' : ''}
                  {s.host_display_name ? ` · hosted by ${s.host_display_name}` : ''}
                </p>
                <p className="text-fg-muted text-xs mt-0.5">
                  Room <span className="font-mono">{s.room_code}</span>
                </p>
              </div>
              <div className="flex gap-2 shrink-0">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy !== null}
                  onClick={() => void download(s.session_id, 'export')}
                >
                  <Download size={14} className="mr-1" /> Download scores (CSV)
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy !== null}
                  onClick={() => void download(s.session_id, 'report')}
                >
                  <FileText size={14} className="mr-1" /> Download summary (HTML)
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
