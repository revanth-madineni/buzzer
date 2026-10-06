import { useEffect, useState } from 'react';
import {
  BrowserRouter,
  Navigate,
  NavLink,
  Outlet,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from 'react-router-dom';
import { Gamepad2, History, Image, LogOut, Play, Users } from 'lucide-react';
import { api } from './lib/api';
import LoginPage from './pages/LoginPage';
import HomePage from './pages/HomePage';
import GameLayout from './pages/game/GameLayout';
import LobbyPage from './pages/game/LobbyPage';
import QuestionPage from './pages/game/QuestionPage';
import ResultsPage from './pages/game/ResultsPage';
import GameOverPage from './pages/game/GameOverPage';
import GamesPage from './pages/manage/GamesPage';
import QuestionEditorPage from './pages/manage/QuestionEditorPage';
import RosterPage from './pages/manage/RosterPage';
import SessionsPage from './pages/manage/SessionsPage';
import ImagesPage from './pages/manage/ImagesPage';
import { ThemeToggle } from './components/ThemeToggle';

interface Course { id: number; name: string; semester: string }

const SECTIONS = ['games', 'roster', 'images', 'sessions'] as const;

function RequireAuth({ children }: { children: React.ReactNode }) {
  if (!localStorage.getItem('token')) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

/** Management area for one course: course picker, section links, Play, Sign out. */
function HostLayout() {
  const { courseId } = useParams<{ courseId: string }>();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const [courses, setCourses] = useState<Course[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    api
      .get<Course[]>('/game/my-courses')
      .then(setCourses)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load courses'));
  }, []);

  // The section after /courses/:courseId/ — a game's question editor maps to "games".
  const section = SECTIONS.find((s) => pathname.split('/')[3] === s) ?? 'games';

  function switchCourse(id: string) {
    navigate(`/courses/${id}/${section}`);
  }

  function logout() {
    localStorage.removeItem('token');
    navigate('/login');
  }

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
      isActive ? 'bg-accent text-on-accent' : 'text-fg hover:bg-surface-hover'
    }`;

  return (
    <div className="flex min-h-screen">
      <aside className="w-60 shrink-0 bg-surface border-r border-line flex flex-col">
        <div className="px-4 py-5 border-b border-line space-y-2">
          <h1 className="text-lg font-bold text-fg px-2">Manage Course</h1>
          <select
            value={courseId}
            onChange={(e) => switchCourse(e.target.value)}
            className="w-full rounded-lg border border-line-strong bg-surface-alt px-3 py-2 text-sm text-fg"
          >
            {!courses.some((c) => String(c.id) === courseId) && <option value={courseId}>Course {courseId}</option>}
            {courses.map((c) => (
              <option key={c.id} value={c.id}>{c.name} — {c.semester}</option>
            ))}
          </select>
          {error && <p className="text-danger-fg text-xs px-2">{error}</p>}
        </div>
        <nav className="flex-1 p-3 space-y-1">
          <NavLink to={`/courses/${courseId}/games`} className={linkClass}>
            <Gamepad2 size={16} /> Games
          </NavLink>
          <NavLink to={`/courses/${courseId}/roster`} className={linkClass}>
            <Users size={16} /> Roster
          </NavLink>
          <NavLink to={`/courses/${courseId}/images`} className={linkClass}>
            <Image size={16} /> Images
          </NavLink>
          <NavLink to={`/courses/${courseId}/sessions`} className={linkClass}>
            <History size={16} /> Sessions
          </NavLink>
        </nav>
        <div className="p-3 border-t border-line space-y-1">
          <NavLink to="/home" className={linkClass}>
            <Play size={16} /> Play
          </NavLink>
          <ThemeToggle showLabel className="w-full justify-start gap-3 px-4" />
          <button
            onClick={logout}
            className="flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium text-fg hover:bg-surface-hover w-full transition-colors"
          >
            <LogOut size={16} /> Sign out
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter basename={import.meta.env.BASE_URL}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/home" element={<RequireAuth><HomePage /></RequireAuth>} />
        <Route path="/courses/:courseId" element={<RequireAuth><HostLayout /></RequireAuth>}>
          <Route index element={<Navigate to="games" replace />} />
          <Route path="games" element={<GamesPage />} />
          <Route path="games/:gameId/questions" element={<QuestionEditorPage />} />
          <Route path="roster" element={<RosterPage />} />
          <Route path="images" element={<ImagesPage />} />
          <Route path="sessions" element={<SessionsPage />} />
        </Route>
        <Route path="/game/:code" element={<RequireAuth><GameLayout /></RequireAuth>}>
          <Route path="lobby" element={<LobbyPage />} />
          <Route path="question" element={<QuestionPage />} />
          <Route path="results" element={<ResultsPage />} />
          <Route path="gameover" element={<GameOverPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
