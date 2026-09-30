# frontend/admin/src/pages/

## Purpose
Route components for the admin (desktop) app: CRUD for courses, rosters, local users, guests,
games and questions; granting per-user course and game access; and browsing, exporting, and
deleting game sessions. Plain REST only; no socket, no live game view. Every page is a
self-contained `useState` + `load()` component with no shared store.

## Contents
Routes are defined in `../App.tsx` (basename `/admin/` in production). Everything except
`/login` sits inside `RequireAdmin` (token-present check only) and `AdminLayout` (sidebar:
Courses, Users, Games, Guests, Sessions, Logout). Unknown paths → `/courses`.
- `LoginPage.tsx` — `/login`: username + password → `POST /auth/login` → `/courses`. No NetID
  SSO and no role check.
- `CoursesPage.tsx` — `/courses`: list, create, and rename courses (name + semester). Each row
  links to its roster. No delete (there's no endpoint).
- `RosterPage.tsx` — `/courses/:courseId/roster`: active/inactive roster lists with inline edit
  (netid, name, email, `is_active`), plus a CSV import wizard: pick file → client-side
  RFC-4180 parse → auto-detect columns (Canvas gradebook: `SIS Login ID` / `Student`, skip the
  "Points Possible" row, strip `@domain`, keep given name) → mapping with a 3-row preview →
  `POST .../roster/import {rows}` → counts of imported/updated/deactivated + errors.
- `UsersPage.tsx` — `/users`: all non-GUEST users (ADMIN and USER) and a "Create Local
  Account" form (username, display name, password, optional email; created as `USER`). Rows
  link to `/users/:userId`.
- `UserDetailPage.tsx` — `/users/:userId`: profile edit (username only for local accounts,
  display name, email, new password, global role `USER | ADMIN`), delete (hidden for ADMINs),
  and the two **access panels**:
  - **Course access**: list with revoke, plus "grant" as a checkbox list of *ungranted* courses,
    each with a HOST/PLAYER toggle (default HOST) → one `POST .../course-access` per course.
  - **Game access**: list with revoke, plus a checkbox list of ungranted games →
    `POST .../game-access` each.
- `GuestsPage.tsx` — `/guests`: GUEST users (name, email, UUID), delete, and "Merge Guest into
  Real User" by guest UUID ("Use ID" fills it) + target netid.
- `GamesPage.tsx` — `/games`: list, create, and edit games (title, description, `max_players`);
  JSON import (`postForm`, then jump to the new game's questions); delete (browser confirm).
- `QuestionEditorPage.tsx` — `/games/:gameId/questions`: ordered question list with up/down
  reorder (`POST .../reorder` with the full id order), inline add/edit via `QuestionForm`,
  delete, and JSON export. `formToPayload` builds `config` / `answer_data` per type and
  **derives `points_value`**: max option points (MC, FIB), max of T/F, sum of positive options
  (multi-select), or the entered value for COMPLETENESS.
- `SessionsPage.tsx` — `/sessions`: all sessions with status filter tabs (course, game, host,
  player count, dates). Per session: HTML report download, delete (two-step confirm), and an
  expandable export panel. Canvas CSV has a column title + optional assignment ID (appended to
  the title), SIS domain (default `wisc.edu`), roster-only, and per-question options; raw CSV
  has none.

## How it fits in
Uses `lib/api.ts` (see `lib/CLAUDE.md` for the full endpoint-per-page table) and
`components/ui/*` (see `components/CLAUDE.md`). No `types/` directory: each page declares its
own response interfaces inline, mirroring `backend/app/schemas/`.

### Roles and access: what this app writes, and who reads it
Two separate role systems (see `backend/app/models/CLAUDE.md`):
- **Global `User.role`** (`ADMIN | USER | GUEST`): set by `UserDetailPage`'s role picker
  (USER ↔ ADMIN only). Local accounts from `UsersPage` start as `USER`. NetID users are
  auto-created as `USER` on first SSO login. GUESTs are created by the player app's guest join
  and only appear on `GuestsPage`.
- **Per-course `UserCourseAccess.role`** (`HOST | PLAYER`) and **per-game `UserGameAccess`**:
  granted in `UserDetailPage`. These are what the **host app** reads. `my-courses` lists
  HOST courses, `my-games` lists granted games, and `POST /game/rooms` requires **both** HOST
  on the chosen course **and** a grant on the chosen game. ADMINs bypass all of it, so grants
  on an ADMIN user are shown but have no effect.
- **Games are not tied to courses.** `GamesPage` has no course field and there's no
  game ↔ course link anywhere. To let someone run game G in course C, grant them HOST on C
  **and** access to G, separately, on their user page. There's no "who can host this
  game/course" view from the game or course side.
- **Roster ≠ course access.** `CourseRoster` rows (keyed by netid, not a user FK) are what
  let a student **join as a player**. `authorise_player` accepts an active roster row **or** a
  `UserCourseAccess` PLAYER/HOST row. Roster entries grant nothing on the host side.
- Every call here is admin-only (`require_admin`) except `DELETE /game/sessions/{id}` in
  `SessionsPage`, which is the host endpoint and works for admins via the ADMIN-or-owner check.

## Gotchas
- **No client-side admin gate.** Any local `USER` can log in here and gets the full sidebar;
  every page then shows a bare `HTTP 403` (see `lib/CLAUDE.md`).
- **Roster import deactivates everyone not in the upload.** The backend deactivates every entry
  missing from `rows`, and the wizard **silently drops** any row with a blank netid, name, **or
  email** before sending (`mapRow(..., skipBlank = true)`). So a student with no email in the
  CSV, or a partial file, gets deactivated and can't join as a player via the roster. The
  preview shows only the kept-row count, not which rows were dropped.
- **"Reverse name" keeps only the given name.** `Last, First Middle` becomes `First Middle`.
  The surname is discarded, matching `roster_service.process_roster_csv`. That name is what
  players see in-game. Title-casing uses `\b\w`, which mangles non-ASCII names (`élodie` →
  `éLodie`).
- **Changing a course role needs a revoke first.** The grant panel only lists *ungranted*
  courses, so switching HOST ↔ PLAYER means revoke, then re-grant, even though the backend's
  `POST .../course-access` already upserts the role.
- **Bulk grants are not atomic.** One request per checked course/game via `Promise.all`. A
  partial failure shows one error, but the successful grants stay.
- **Admins can demote themselves or the last admin.** The role picker has no guard (neither
  does `PUT /admin/users/{id}`). Demoting yourself locks you out on the next request.
- **Destructive actions go further than the confirm text says:**
  - `DELETE /admin/games/{id}`: "Delete this game and all its sessions?" also deletes every score
    and doesn't stop a live room.
  - Session delete is offered for LOBBY/IN_PROGRESS sessions too, and connected players aren't
    notified.
  - Guest/user delete removes all their scores.
- **Guest merge is by raw UUID + netid** with no preview. Backend-wise (see
  `routers/CLAUDE.md`), if no user has that netid the guest is **promoted in place** to a
  `USER`. The success message says "merged" either way.
- **Question edits aren't guarded against live games.** Edit, delete, and reorder hit the
  backend with no live-session check, and the backend doesn't validate structure on `PUT` /
  reorder (see `schemas/CLAUDE.md`). Deleting a question that already has scores fails with an
  FK error surfaced as `HTTP 500`.
- **`points_value` can disagree with the saved options.** Multi-select and fill-in-the-blank
  drop blank-text options/answers from the payload, but `points_value` is computed over **all**
  of them, blanks included. MC doesn't drop blank options at all.
- **Answer data key naming is inconsistent by type.** MC/TF/multi-select use `answer_points`
  (snake_case); fill-in-the-blank uses `acceptedAnswers` / `answerPoints` / `editDistance`
  (camelCase). These must match `services/game_service.calculate_score` and the host app's
  reveal rendering. A new question type touches `FormState`, `defaultForm`,
  `questionToForm`, `formToPayload`, the `QuestionForm` UI, and the list rendering here, plus
  the backend and both game frontends.
- **`max_players` is editable but never enforced** by the server (see `websocket/CLAUDE.md`).
- **Literal escape sequences render on screen.** `Loading…` in JSX text (not inside
  `{'…'}`) shows the backslash sequence verbatim. This happens in `UsersPage`, `GuestsPage`,
  `GamesPage`, `QuestionEditorPage` (loading), and the `(±…` edit-distance label in
  `QuestionEditorPage`'s list.
- Reorder sends the full order after a single swap. Two admins editing the same game will
  overwrite each other. The list isn't reloaded after reorder, only the local swap applied.
- `SessionsPage` export options are kept per session in component state and lost on navigation.
  The Canvas "assignment ID" is only appended to the column title, not sent as a separate field.
