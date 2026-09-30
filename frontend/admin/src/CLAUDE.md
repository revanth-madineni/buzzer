# frontend/admin/src/

## Purpose
The admin app: a React + Vite + Tailwind single-page desktop app for staff. It manages
courses and their student rosters, local user accounts and guests, games and their questions,
per-user course (HOST/PLAYER) and game access grants, and past/live sessions (Canvas or raw
CSV export, HTML report, delete). Plain REST only; it never opens a socket or shows a live
game.

## Contents
Top-level files:
- `main.tsx` — Mounts `<App />` in `StrictMode` and imports `index.css`.
- `App.tsx` — `react-router` routes under basename `import.meta.env.BASE_URL` (`/admin/` in
  production, `/` in dev). `/login` is public. Everything else sits inside `RequireAdmin`
  (despite the name, it only checks that `localStorage.token` is **present**) and
  `AdminLayout` (sidebar: Courses, Users, Games, Guests, Sessions, Logout):
  `/courses`, `/courses/:courseId/roster`, `/users`, `/users/:userId`, `/guests`, `/games`,
  `/games/:gameId/questions`, `/sessions`. Anything else redirects to `/courses`.
- `index.css` — Tailwind directives and global dark-slate body styles.

There's no `types/` directory. Each page declares its own response interfaces inline.

Subdirectories (each has its own `CLAUDE.md`):
| dir | role |
|---|---|
| `lib/` | `api.ts` REST wrapper with `get`/`post`/`put`/`patch`/`delete`, `postForm` (multipart upload) and `download` (Blob + `Content-Disposition` filename); `cn()`. No role logic. |
| `components/` | `ui/` primitives only (`Button`, `Card`, `Input`), byte-identical to the host app's. Selects, textareas, toggles and confirms are built inline in pages. |
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
  - Per-course `UserCourseAccess.role` (`HOST | PLAYER`) and per-game `UserGameAccess`, both
    granted in `UserDetailPage`.
- **Who reads them.** The **host app's** `my-courses`, `my-games`, and `POST /game/rooms` read
  the per-course and per-game grants. Creating a room needs HOST on the course **and** the game
  grant. ADMIN bypasses both, so grants on an ADMIN user have no effect.
- **Games have no course.** To let someone run game G in course C, grant HOST on C **and**
  access to G separately. There's no game ↔ course link, and no "who can host this" view from
  the game or course side.
- **Roster ≠ course access.** `CourseRoster` rows (keyed by netid, not a user FK) let a student
  **join as a player**, as does a `UserCourseAccess` PLAYER/HOST row. Roster rows grant nothing
  on the host side.

### Typical setup for a new course
1. `CoursesPage`: create the course.
2. `RosterPage`: import the Canvas gradebook CSV (column-mapping wizard →
   `POST .../roster/import`).
3. `GamesPage`: create a game or import JSON, then `QuestionEditorPage` to add/edit/reorder
   questions.
4. `UsersPage` / `UserDetailPage`: make sure the instructor exists (NetID users appear after
   their first SSO login), then grant HOST on the course **and** access to the game.
5. After the game has run, on `SessionsPage`: Canvas CSV export or the HTML report.

## Gotchas
Most important cross-cutting issues. Details are in each subdirectory's file.
- **No client-side admin gate.** `/auth/login` issues tokens to any local account, and
  `RequireAdmin` never checks the role. A non-admin gets the full UI and a bare `HTTP 403` on
  every page (`lib/CLAUDE.md`). NetID-only admins can't log in at all (no SSO button).
- **Token collision with the host/player apps.** All three use `localStorage.token` on one
  origin. A guest join in the player app on the same browser replaces the admin's login.
- **Backend error text is lost.** All three request paths in `api.ts` read `detail`, but
  `BuzzerError` sends `message`, so 403/404/409s show as `HTTP <status>` and 422s as
  `[object Object]`.
- **Roster import can silently lock students out.** The backend deactivates every entry
  missing from the upload, and the wizard drops rows with any blank netid, name, or email
  without listing them. "Reverse name" keeps only the given name, discarding the surname
  (`pages/CLAUDE.md`).
- **Access editing is clunky and non-atomic.** Changing HOST ↔ PLAYER needs a revoke +
  re-grant. Bulk grants are one request each, so a partial failure leaves the successful ones.
  Nothing stops an admin demoting themselves or the last admin.
- **Destructive actions reach further than their confirm text.** Game delete removes every
  session and score and doesn't stop a live room. Session delete works on live games without
  notifying players. User/guest delete removes their scores. Guest merge may promote the
  guest in place.
- **Question editing isn't guarded against live games**, and the backend doesn't validate
  structure on edit/reorder. `points_value` is derived client-side and can include blank
  options that were dropped from the payload. Answer-data keys mix `answer_points` (snake_case)
  with fill-in-the-blank's camelCase, so a new question type touches this app, the backend,
  and both game frontends.
- **Literal `…` / `±` render on screen** in five JSX text spots (`pages/CLAUDE.md`).
- **Duplicated code across apps.** `lib/api.ts` is a superset copy of the host/player
  wrappers, with its error handling repeated three times inside. `components/ui/*` is copied
  from the host app. Fixes don't propagate.
- `StrictMode` double-runs effects in dev, so every page's `load()` fires twice on mount. That's
  harmless (reads only).
