import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader } from '../components/ui/card';
import { ThemeToggle } from '../components/ThemeToggle';

interface Course { id: number; name: string; semester: string }
interface Game { id: number; title: string; course_id: number | null }
interface ActiveSession {
  session_id: string;
  room_code: string;
  status: string;
  game_title: string;
  course_name: string;
  course_semester: string;
}

export default function HomePage() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [games, setGames] = useState<Game[]>([]);
  const [activeSessions, setActiveSessions] = useState<ActiveSession[]>([]);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [courseId, setCourseId] = useState<number | ''>('');
  const [gameId, setGameId] = useState<number | ''>('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const navigate = useNavigate();

  // A game can only be run in its own course.
  const courseGames = games.filter(g => g.course_id === courseId);

  function selectCourse(id: number | '') {
    setCourseId(id);
    const inCourse = games.filter(g => g.course_id === id);
    setGameId(inCourse.length === 1 ? inCourse[0].id : '');
  }

  useEffect(() => {
    Promise.all([
      api.get<Course[]>('/game/my-courses'),
      api.get<Game[]>('/game/my-games'),
      api.get<ActiveSession[]>('/game/my-active-sessions'),
    ]).then(([c, g, s]) => {
      setCourses(c);
      setGames(g);
      setActiveSessions(s);
      if (c.length === 1) {
        setCourseId(c[0].id);
        const inCourse = g.filter(x => x.course_id === c[0].id);
        if (inCourse.length === 1) setGameId(inCourse[0].id);
      }
      setLoaded(true);
    }).catch(() => setError('Failed to load courses or games. Are you still logged in?'));
  }, []);

  async function deleteSession(sessionId: string) {
    try {
      await api.delete(`/game/sessions/${sessionId}`);
      setActiveSessions(prev => prev.filter(s => s.session_id !== sessionId));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete session');
    } finally {
      setConfirmDelete(null);
    }
  }

  async function createRoom() {
    if (!courseId || !gameId) return;
    setError('');
    setLoading(true);
    try {
      const data = await api.post<{ room_code: string }>('/game/rooms', {
        course_id: courseId,
        game_id: gameId,
      });
      navigate(`/game/${data.room_code}/lobby`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create room');
      setLoading(false);
    }
  }

  function logout() {
    localStorage.removeItem('token');
    navigate('/login');
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-4 gap-4">
      <ThemeToggle className="fixed top-4 right-4 z-40" />
      {activeSessions.length > 0 && (
        <Card className="w-full max-w-lg border-warning">
          <CardHeader>
            <h2 className="text-lg font-semibold text-warning-fg">Active Sessions</h2>
            <p className="text-fg-muted text-sm">You have running games — rejoin one or create a new room below.</p>
          </CardHeader>
          <CardContent className="space-y-2">
            {activeSessions.map(s => (
              <div
                key={s.session_id}
                className="flex items-center justify-between rounded-lg bg-surface-alt border border-line px-4 py-3"
              >
                <div>
                  <p className="text-fg font-medium">{s.game_title}</p>
                  <p className="text-fg-muted text-sm">{s.course_name} · {s.course_semester}</p>
                  <p className="text-fg-muted text-xs mt-0.5">
                    Room <span className="font-mono text-fg">{s.room_code}</span>
                    {' · '}
                    <span className={s.status === 'IN_PROGRESS' ? 'text-success-fg' : 'text-warning-fg'}>
                      {s.status === 'IN_PROGRESS' ? 'In Progress' : 'Lobby'}
                    </span>
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {confirmDelete === s.session_id ? (
                    <>
                      <span className="text-danger-fg text-xs">Delete all data?</span>
                      <Button size="sm" variant="destructive" onClick={() => deleteSession(s.session_id)}>
                        Confirm
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(null)}>
                        Cancel
                      </Button>
                    </>
                  ) : (
                    <>
                      <Button size="sm" variant="outline" onClick={() => navigate(`/game/${s.room_code}/lobby`)}>
                        Rejoin
                      </Button>
                      <Button size="sm" variant="destructive" onClick={() => setConfirmDelete(s.session_id)}>
                        Delete
                      </Button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <Card className="w-full max-w-lg">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold text-fg">Create Game Room</h1>
              <p className="text-fg-muted text-sm mt-1">Select a course and quiz to begin</p>
            </div>
            <Button variant="ghost" size="sm" onClick={logout}>Sign Out</Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {loaded && courses.length === 0 ? (
            <p className="text-fg text-sm">
              You don't host any courses yet — ask an admin for HOST access
            </p>
          ) : (
          <>
          <div>
            <label className="block text-sm font-medium text-fg mb-1">Course</label>
            <div className="flex gap-2">
              <select
                value={courseId}
                onChange={e => selectCourse(e.target.value ? Number(e.target.value) : '')}
                className="flex-1 rounded-lg border border-line-strong bg-surface-alt px-3 py-2 text-fg"
              >
                <option value="">Select a course…</option>
                {courses.map(c => (
                  <option key={c.id} value={c.id}>{c.name} — {c.semester}</option>
                ))}
              </select>
              <Button
                variant="outline"
                disabled={!courseId}
                onClick={() => navigate(`/courses/${courseId}/games`)}
              >
                Manage this course
              </Button>
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-fg mb-1">Quiz</label>
            <select
              value={gameId}
              onChange={e => setGameId(e.target.value ? Number(e.target.value) : '')}
              disabled={!courseId}
              className="w-full rounded-lg border border-line-strong bg-surface-alt px-3 py-2 text-fg"
            >
              <option value="">Select a quiz…</option>
              {courseGames.map(g => (
                <option key={g.id} value={g.id}>{g.title}</option>
              ))}
            </select>
            {courseId !== '' && courseGames.length === 0 && (
              <p className="text-fg-muted text-xs mt-1">
                No quizzes you can run in this course — create one under "Manage this course".
              </p>
            )}
          </div>
          {error && <p className="text-danger-fg text-sm">{error}</p>}
          <Button
            className="w-full"
            size="lg"
            onClick={createRoom}
            disabled={!courseId || !gameId || loading}
          >
            {loading ? 'Creating room…' : 'Create Room'}
          </Button>
          </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
