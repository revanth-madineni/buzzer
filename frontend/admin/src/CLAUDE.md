# frontend/admin/src/

## Purpose
The admin app: a React + Vite + Tailwind single-page desktop app for staff. It leads with
admin tasks (users, courses, and who can host/play/use what) and keeps host tools (games,
sessions, guests) as a secondary section. It manages courses and their student rosters,
local user accounts and guests, games and their questions, per-user course (HOST/PLAYER) and game access grants, and past/live sessions (Canvas or raw
CSV export, HTML report, delete). Plain REST only; it never opens a socket or shows a live
game.

## Contents
Top-level files:
- `main.tsx` — Mounts `<App />` in `StrictMode` and imports `index.css`.
- `App.tsx` — `react-router` routes under basename `import.meta.env.BASE_URL` (`/admin/` in
  production, `/` in dev). `/login` is public. Everything else sits inside `RequireAdmin`
  (despite the name, it only checks that `localStorage.token` is **present**) and
  `AdminLayout`. Its sidebar has two sections: **Admin** (Users, Courses, Access) and **Host
  tools** (Games, Sessions, Guests), plus Logout. Routes: `/users`, `/users/:userId`,
  `/courses`, `/courses/:courseId/roster`, `/access`, `/games`, `/games/:gameId/questions`,
  `/sessions`, `/guests`. Anything else, and a successful login, goes to `/users`.
- `index.css` — Tailwind directives and global dark-slate body styles.

There's no `types/` directory. Each page declares its own response interfaces inline.

Subdirectories (each has its own `CLAUDE.md`):
| dir | role |
|---|---|
| `lib/` | `api.ts` REST wrapper with `get`/`post`/`put`/`patch`/`delete`, `postForm` (multipart upload) and `download` (Blob + `Content-Disposition` filename), showing the server's error `message`; `cn()`; (T7) `mapPin.ts` and `images.ts`, byte-identical across all three apps. No role logic. `api.ts` is identical to the host app's. |
| `components/` | `ui/` primitives (`Button`, `Card`, `Input`), byte-identical to the host app's, `MoveGamePanel` (the move/assign-with-preview flow shared by `GamesPage` and `AccessPage`), and (T7) `MapCanvas` for placing map-pin targets. |
| `pages/` | One self-contained page per route (`useState` + `load()`, no shared store). |

## How it fits together
Dependency direction: `pages/` → `components/` + `lib/`. The only persistent client state is
`localStorage.token`, shared with the host and player apps (see Gotchas). In dev, Vite serves
on :5175 and proxies `/api` to `localhost:8000`. Behind nginx, it's same-origin under
`/admin/`.

### Endpoints
Every call is under `/api/admin/*` and guarded by `require_admin`, with two exceptions:
- `LoginPage` → `POST /auth/login` (username + password only; no NetID SSO).
- `SessionsPage` → `DELETE /game/sessions/{id}`, the **host** endpoint, which admins pass via
  its ADMIN-or-owner check. There's no admin-specific session delete.

`lib/CLAUDE.md` has the full endpoint-per-page table.

### Roles and access: this app is where they're written
- **Two role systems** (`backend/app/models/CLAUDE.md`):
  - Global `User.role` (`ADMIN | USER | GUEST`), set by `UserDetailPage`'s picker
    (USER ↔ ADMIN). Local accounts from `UsersPage` start as `USER`, NetID users are
    auto-created as `USER` on first SSO login, and GUESTs come from the player app's guest join.
  - Per-course `UserCourseAccess.role` (`HOST | PLAYER`) and per-game `UserGameAccess`, granted
    in `AccessPage` (per course) or `UserDetailPage` (per user).
- **Who reads them.** The host app (`my-courses`, `my-games`, `POST /game/rooms`, and its
  management area) and the backend's `/api/host/*`. A non-admin can use game G iff they hold
  HOST on G's course, plus a grant if G is `restricted`. ADMIN bypasses all of it, so grants on
  an ADMIN user have no effect.
- **Games belong to a course** (T4). `GamesPage` requires a course on create and import.
  "Move / assign" changes it, after previewing which grants would stop working.
  `AccessPage` is the "who can host this course / use this game" view.
- **Roster ≠ course access.** `CourseRoster` rows (keyed by netid, not a user FK) let a student
  **join as a player**, as does a `UserCourseAccess` PLAYER/HOST row. Roster rows grant nothing
  on the host side.

### Typical setup for a new course
1. `CoursesPage`: create the course (choose whether guests may join).
2. `UsersPage`: make sure the instructor exists (NetID users appear after their first SSO
   login).
3. `AccessPage`: grant the instructor HOST on the course.
4. From here the instructor can upload the roster and create games/questions in the host app.
   Alternatively, the admin does it here: `RosterPage` (column-mapping wizard), then
   `GamesPage` + `QuestionEditorPage`.
5. After the game has run: hosts download CSV/HTML from the host app; the admin also has Canvas
   CSV and the HTML report on `SessionsPage`.

## Gotchas
Most important cross-cutting issues. Details are in each subdirectory's file.
- **No client-side admin gate.** `/auth/login` issues tokens to any local account, and
  `RequireAdmin` never checks the role. A non-admin gets the full UI and "Admin access
  required" on every page (`lib/CLAUDE.md`). NetID-only admins can't log in at all (no SSO button).
- **Token collision with the host/player apps.** All three use `localStorage.token` on one
  origin. A guest join in the player app on the same browser replaces the admin's login.
- **Error text.** Since T4, `api.ts` shows the server's `message` (e.g. `GAME_LIVE`'s "This game
  is being played right now"); 422 validation errors show only "Invalid input".
- **Roster import can silently lock students out.** The backend deactivates every entry
  missing from the upload, and the wizard drops rows with any blank netid, name, or email
  without listing them. "Reverse name" keeps only the given name, discarding the surname
  (`pages/CLAUDE.md`).
- **Access editing is non-atomic.** `AccessPage` switches HOST ↔ PLAYER in one step, but
  `UserDetailPage` still needs a revoke + re-grant. Bulk grants are one request each, so a
  partial failure leaves the successful ones. Nothing stops an admin demoting themselves or the
  last admin.
- **Destructive actions reach further than their confirm text.** Game delete removes every
  session and score and doesn't stop a live room. Session delete works on live games without
  notifying players. User/guest delete removes their scores. Guest merge may promote the
  guest in place.
- **Question edits during a live game are refused** server-side (409 `GAME_LIVE`), as is
  deleting an answered question (409 `QUESTION_HAS_ANSWERS`). Since T7 the backend
  validates the whole merged question on edit. `points_value` is derived client-side and can
  include blank options that were dropped from the payload. Answer-data keys mix `answer_points` (snake_case)
  with fill-in-the-blank's camelCase, so a new question type touches this app, the backend,
  and both game frontends.
- **Literal `…` / `±` render on screen** in five JSX text spots (`pages/CLAUDE.md`).
- **Duplicated code across apps.** `lib/api.ts` and `components/ui/*` are identical copies of
  the host app's, and the host's `pages/manage/QuestionEditorPage.tsx` is an adapted copy of
  this app's `QuestionEditorPage`. Fixes don't propagate.
- `StrictMode` double-runs effects in dev, so every page's `load()` fires twice on mount. That's
  harmless (reads only).
