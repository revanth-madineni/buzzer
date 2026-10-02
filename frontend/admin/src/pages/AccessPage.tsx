import { useEffect, useState } from 'react';
import { AlertTriangle, Lock, Trash2 } from 'lucide-react';
import { api } from '../lib/api';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader } from '../components/ui/card';
import { MoveGamePanel, type MoveCourse } from '../components/MoveGamePanel';

interface User {
  id: string;
  username: string | null;
  netid: string | null;
  display_name: string | null;
  role: string;
}

interface CourseAccessEntry {
  user_id: string;
  username: string | null;
  netid: string | null;
  display_name: string | null;
  role: 'HOST' | 'PLAYER';
}

interface GameAccessEntry {
  user_id: string;
  username: string | null;
  netid: string | null;
  display_name: string | null;
  has_course_host: boolean;
}

interface Game {
  id: number;
  title: string;
  course_id: number | null;
  restricted: boolean;
}

type Person = { display_name: string | null; username: string | null; netid: string | null };

function personLabel(u: Person): string {
  const name = u.display_name || u.username || u.netid || '?';
  const id = u.netid || u.username;
  return id && id !== name ? `${name} (${id})` : name;
}

const selectClass =
  'rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500';

function UserPicker({
  users,
  exclude,
  value,
  onChange,
}: {
  users: User[];
  exclude: Set<string>;
  value: string;
  onChange: (id: string) => void;
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={`${selectClass} flex-1`}>
      <option value="">Select a user…</option>
      {users
        .filter((u) => !exclude.has(u.id))
        .map((u) => (
          <option key={u.id} value={u.id}>{personLabel(u)}</option>
        ))}
    </select>
  );
}

export default function AccessPage() {
  const [courses, setCourses] = useState<MoveCourse[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [courseId, setCourseId] = useState<number | ''>('');
  const [error, setError] = useState('');

  useEffect(() => {
    Promise.all([api.get<MoveCourse[]>('/admin/courses'), api.get<User[]>('/admin/users')])
      .then(([cs, us]) => { setCourses(cs); setUsers(us); })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load'));
  }, []);

  return (
    <div className="p-8 max-w-4xl space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-100">Access</h2>
        <p className="text-slate-400 text-sm mt-1">
          Who can host and play in a course, and which hosts can use its restricted games.
        </p>
      </div>
      <select
        value={courseId}
        onChange={(e) => setCourseId(e.target.value ? Number(e.target.value) : '')}
        className={`${selectClass} w-full`}
      >
        <option value="">Select a course…</option>
        {courses.map((c) => (
          <option key={c.id} value={c.id}>{c.name} — {c.semester}</option>
        ))}
      </select>
      {error && <p className="text-red-400 text-sm">{error}</p>}
      {courseId !== '' && <CourseAccess key={courseId} courseId={courseId} courses={courses} users={users} />}
    </div>
  );
}

function CourseAccess({ courseId, courses, users }: { courseId: number; courses: MoveCourse[]; users: User[] }) {
  const [members, setMembers] = useState<CourseAccessEntry[]>([]);
  const [games, setGames] = useState<Game[]>([]);
  const [newUser, setNewUser] = useState('');
  const [newRole, setNewRole] = useState<'HOST' | 'PLAYER'>('HOST');
  const [assigning, setAssigning] = useState<number | null>(null);
  const [error, setError] = useState('');

  async function load() {
    try {
      const [m, gs] = await Promise.all([
        api.get<CourseAccessEntry[]>(`/admin/courses/${courseId}/access`),
        api.get<Game[]>('/admin/games'),
      ]);
      setMembers(m);
      setGames(gs);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load access');
    }
  }

  useEffect(() => { void load(); }, [courseId]);

  async function run(action: () => Promise<unknown>, fallback: string) {
    setError('');
    try {
      await action();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : fallback);
    }
  }

  // POST course-access upserts, so it also switches HOST <-> PLAYER.
  const setRole = (userId: string, role: 'HOST' | 'PLAYER') =>
    run(() => api.post(`/admin/users/${userId}/course-access`, { course_id: courseId, role }), 'Grant failed');

  const courseGames = games.filter((g) => g.course_id === courseId);
  const unassigned = games.filter((g) => g.course_id === null);

  return (
    <>
      {error && <p className="text-red-400 text-sm">{error}</p>}

      <Card>
        <CardHeader><h3 className="font-semibold text-slate-100">Course hosts and players</h3></CardHeader>
        <CardContent className="space-y-3">
          {members.length === 0 && <p className="text-slate-500 text-sm">Nobody has access to this course yet.</p>}
          {members.map((m) => (
            <div key={m.user_id} className="flex items-center justify-between gap-3">
              <span className="text-slate-200 text-sm">{personLabel(m)}</span>
              <div className="flex items-center gap-2">
                <select
                  value={m.role}
                  onChange={(e) => void setRole(m.user_id, e.target.value as 'HOST' | 'PLAYER')}
                  className={selectClass}
                >
                  <option value="HOST">HOST</option>
                  <option value="PLAYER">PLAYER</option>
                </select>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    void run(() => api.delete(`/admin/users/${m.user_id}/course-access/${courseId}`), 'Revoke failed')
                  }
                >
                  <Trash2 size={12} />
                </Button>
              </div>
            </div>
          ))}
          <div className="flex gap-2 pt-2 border-t border-slate-700">
            <UserPicker
              users={users}
              exclude={new Set(members.map((m) => m.user_id))}
              value={newUser}
              onChange={setNewUser}
            />
            <select value={newRole} onChange={(e) => setNewRole(e.target.value as 'HOST' | 'PLAYER')} className={selectClass}>
              <option value="HOST">HOST</option>
              <option value="PLAYER">PLAYER</option>
            </select>
            <Button
              size="sm"
              disabled={!newUser}
              onClick={() => { void setRole(newUser, newRole); setNewUser(''); }}
            >
              Grant
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <h3 className="font-semibold text-slate-100">Games in this course</h3>
          <p className="text-slate-400 text-sm">
            Every HOST of the course can use an unrestricted game. A restricted game also needs a grant.
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          {courseGames.length === 0 && <p className="text-slate-500 text-sm">No games in this course.</p>}
          {courseGames.map((g) => (
            <GameAccess key={g.id} game={g} users={users} onChanged={load} />
          ))}
        </CardContent>
      </Card>

      {unassigned.length > 0 && (
        <Card>
          <CardHeader>
            <h3 className="font-semibold text-slate-100">Unassigned games</h3>
            <p className="text-slate-400 text-sm">Only admins can run these until they belong to a course.</p>
          </CardHeader>
          <CardContent className="space-y-3">
            {unassigned.map((g) => (
              <div key={g.id} className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-slate-200 text-sm">{g.title}</span>
                  {assigning !== g.id && (
                    <Button size="sm" variant="outline" onClick={() => setAssigning(g.id)}>
                      Assign to this course
                    </Button>
                  )}
                </div>
                {assigning === g.id && (
                  <MoveGamePanel
                    game={g}
                    courses={courses}
                    fixedCourseId={courseId}
                    onDone={() => { setAssigning(null); void load(); }}
                    onCancel={() => setAssigning(null)}
                  />
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </>
  );
}

function GameAccess({ game, users, onChanged }: { game: Game; users: User[]; onChanged: () => Promise<void> }) {
  const [holders, setHolders] = useState<GameAccessEntry[]>([]);
  const [newUser, setNewUser] = useState('');
  const [error, setError] = useState('');

  async function load() {
    try {
      setHolders(await api.get<GameAccessEntry[]>(`/admin/games/${game.id}/access`));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load grants');
    }
  }

  useEffect(() => { void load(); }, [game.id]);

  async function run(action: () => Promise<unknown>, fallback: string, refreshGames = false) {
    setError('');
    try {
      await action();
      await load();
      if (refreshGames) await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : fallback);
    }
  }

  return (
    <div className="rounded-lg border border-slate-700 p-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="font-medium text-slate-100 flex items-center gap-2">
          {game.title}
          {game.restricted && <Lock size={12} className="text-amber-400" />}
        </span>
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={game.restricted}
            onChange={() =>
              void run(() => api.put(`/admin/games/${game.id}`, { restricted: !game.restricted }), 'Update failed', true)
            }
          />
          Restricted
        </label>
      </div>

      {game.restricted && holders.length === 0 && (
        <p className="flex items-center gap-1 text-amber-400 text-xs">
          <AlertTriangle size={12} /> Only admins can run this game — grant a host or un-restrict it.
        </p>
      )}
      {holders.map((h) => (
        <div key={h.user_id} className="flex items-center justify-between text-sm">
          <span className="text-slate-300">
            {personLabel(h)}
            {!h.has_course_host && (
              <span className="ml-2 text-amber-400 text-xs">
                <AlertTriangle size={11} className="inline mr-0.5" />
                not a HOST of this course — this grant has no effect
              </span>
            )}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void run(() => api.delete(`/admin/users/${h.user_id}/game-access/${game.id}`), 'Revoke failed')}
          >
            <Trash2 size={12} />
          </Button>
        </div>
      ))}
      <div className="flex gap-2">
        <UserPicker users={users} exclude={new Set(holders.map((h) => h.user_id))} value={newUser} onChange={setNewUser} />
        <Button
          size="sm"
          variant="outline"
          disabled={!newUser}
          onClick={() => {
            void run(() => api.post(`/admin/users/${newUser}/game-access`, { game_id: game.id }), 'Grant failed');
            setNewUser('');
          }}
        >
          Grant game
        </Button>
      </div>
      {error && <p className="text-red-400 text-xs">{error}</p>}
    </div>
  );
}
