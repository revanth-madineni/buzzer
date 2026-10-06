import { BrowserRouter, Navigate, Outlet, Route, Routes, useNavigate, NavLink } from 'react-router-dom';
import { BookOpen, Users, Gamepad2, UserX, LogOut, History, KeyRound } from 'lucide-react';
import LoginPage from './pages/LoginPage';
import CoursesPage from './pages/CoursesPage';
import RosterPage from './pages/RosterPage';
import UsersPage from './pages/UsersPage';
import UserDetailPage from './pages/UserDetailPage';
import GuestsPage from './pages/GuestsPage';
import GamesPage from './pages/GamesPage';
import QuestionEditorPage from './pages/QuestionEditorPage';
import SessionsPage from './pages/SessionsPage';
import AccessPage from './pages/AccessPage';
import { ThemeToggle } from './components/ThemeToggle';

function RequireAdmin() {
  const token = localStorage.getItem('token');
  if (!token) return <Navigate to="/login" replace />;
  return <Outlet />;
}

function AdminLayout() {
  const navigate = useNavigate();

  function logout() {
    localStorage.removeItem('token');
    navigate('/login');
  }

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
      isActive
        ? 'bg-indigo-600 text-white'
        : 'text-slate-300 hover:bg-slate-700 hover:text-slate-100'
    }`;

  const sectionClass = 'px-4 pb-1 text-xs font-semibold uppercase tracking-wide text-slate-500';

  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="w-56 shrink-0 bg-slate-900 border-r border-slate-700 flex flex-col">
        <div className="px-6 py-5 border-b border-slate-700">
          <h1 className="text-lg font-bold text-white">Buzzer Admin</h1>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          <p className={sectionClass}>Admin</p>
          <NavLink to="/users" className={linkClass}>
            <Users size={16} /> Users
          </NavLink>
          <NavLink to="/courses" className={linkClass}>
            <BookOpen size={16} /> Courses
          </NavLink>
          <NavLink to="/access" className={linkClass}>
            <KeyRound size={16} /> Access
          </NavLink>
          <p className={`${sectionClass} pt-4`}>Host tools</p>
          <NavLink to="/games" className={linkClass}>
            <Gamepad2 size={16} /> Games
          </NavLink>
          <NavLink to="/sessions" className={linkClass}>
            <History size={16} /> Sessions
          </NavLink>
          <NavLink to="/guests" className={linkClass}>
            <UserX size={16} /> Guests
          </NavLink>
        </nav>
        <div className="p-3 border-t border-slate-700 space-y-1">
          <ThemeToggle showLabel className="w-full justify-start gap-3 px-4" />
          <button
            onClick={logout}
            className="flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium text-slate-300 hover:bg-slate-700 hover:text-slate-100 w-full transition-colors"
          >
            <LogOut size={16} /> Logout
          </button>
        </div>
      </aside>

      {/* Main content */}
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
        <Route element={<RequireAdmin />}>
          <Route element={<AdminLayout />}>
            <Route path="/courses" element={<CoursesPage />} />
            <Route path="/courses/:courseId/roster" element={<RosterPage />} />
            <Route path="/users" element={<UsersPage />} />
            <Route path="/users/:userId" element={<UserDetailPage />} />
            <Route path="/guests" element={<GuestsPage />} />
            <Route path="/games" element={<GamesPage />} />
            <Route path="/games/:gameId/questions" element={<QuestionEditorPage />} />
            <Route path="/sessions" element={<SessionsPage />} />
            <Route path="/access" element={<AccessPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/users" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
