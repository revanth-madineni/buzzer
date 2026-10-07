# Course delete (admin)

Status: **built**. Branch `feat/course-delete`.

## 1. Problem

There is no way to delete a course. The integration tests create a fresh course per test
(`tests/integration/conftest.py` `game_setup`: "Test Course <tag>"; `t4_helpers.T4World.course`:
"T4 Course <tag><n>") and leave it behind on purpose, because nothing can remove it. A dev
database collects hundreds of them (713 on one machine), and every course picker in the admin
and host apps fills with junk. T5 asks that every creation path have a matching cleanup path;
courses are the one the tests can't clean.

Fix: an admin-only endpoint that deletes an **empty** course, a Delete button on the admin
Courses page, and test teardown that uses it.

## 2. Technical plan

- **`DELETE /api/admin/courses/{course_id}`**, admin only, 204 on success.
- **Empty** means: no game has `course_id` = this course, no game session has `course_id` =
  this course (sessions keep the course they were played in, even after their game moves), and
  no image has `course_id` = this course. Anything else → **409 `COURSE_NOT_EMPTY`**, with a
  message that names the counts and nothing deleted.
- Roster rows (`course_rosters`) and course access grants (`user_course_access`) are **deleted
  with the course**. Both already have `ON DELETE CASCADE` at the database (migration 001;
  `models/course.py`), so the endpoint does nothing extra for them. The UI confirm says so.
- The delete is a **Core `DELETE` statement**, not ORM `db.delete(course)`, so only the
  database's foreign keys decide what happens (see §4.1).
- **No host endpoint.** Only admins create courses (`POST /admin/courses`), so only admins
  delete them.
- **No Redis work.** A course has no Redis state of its own. Live room state is keyed by
  session, and a course with any session is refused, so nothing can be live.
- **Admin UI:** a Delete button per row on `CoursesPage`, behind the native `confirm()` that
  the other admin pages use; a 409 shows the server's message in the page's error line.
- **Tests:** both teardown paths delete the courses they made, last; new integration tests in
  `tests/integration/test_course_delete.py`.

## 3. Alternatives considered

- **Cascade delete everything** (games, sessions, scores, images). Rejected: it wipes gradebook
  history and exports with one click, and it would have to clear Redis room state for any
  live session. Deleting a course that has been played is a different feature (archive, or
  export-then-delete) and is out of scope.
- **Delete or unassign the course's images automatically.** Rejected: an image delete is
  already its own guarded action (409 `IMAGE_IN_USE`), and silently turning images into
  courseless admin-only images is surprising. Refusing is consistent with games and sessions.
- **Refuse when roster rows or access grants exist.** Rejected: they are course configuration,
  not results, and the database already cascades them. Making the admin clear a roster first
  would just add clicks.
- **Soft delete / archive flag.** Rejected: every course list query (`/admin/courses`,
  `/game/my-courses`, pickers) would need a filter, and the rows would still pile up.
- **Have `conftest.game_setup` reuse one find-or-create "Integration tests" course.**
  Considered, not done. It would stop that fixture's growth without a product change, but
  the T4 tests need a separate course per test (host access is per course), so the endpoint is
  needed anyway. With it, every helper follows one rule: create your own course, delete it in
  teardown.
- **Fix the admin game delete's missing Redis cleanup** (`DELETE /admin/games/{id}` deletes
  sessions from MySQL but not their Redis room keys, unlike the host route). A real but
  separate bug; not part of this feature.

## 4. Detailed implementation

### 4.1 Backend: `backend/app/routers/admin.py`

New handler `delete_course` in the Courses section, after `update_course`:

```
DELETE /courses/{course_id}  status 204
deps: require_admin, get_db
1. course = await db.get(Course, course_id); missing → NotFoundError("Course {id} not found")
   name = course.name   (kept for the log line in step 5)
2. three counts, each SELECT COUNT(*):
     games    = Game.course_id == course_id
     sessions = GameSession.course_id == course_id
     images   = Image.course_id == course_id
3. if any count > 0:
     raise BuzzerError(
       "COURSE_NOT_EMPTY",
       "Can't delete this course: it still has {games} game(s), {sessions} session(s)
        and {images} image(s). Delete or move them first.",
       409,
       extra={"games": games, "sessions": sessions, "images": images},
     )
4. await db.execute(delete(Course).where(Course.id == course_id)); await db.commit()
   - IntegrityError on execute or commit (a game or session was added between the counts
     and the delete) → await db.rollback(), then raise the same COURSE_NOT_EMPTY 409 with
     the message "Can't delete this course: something was added to it while deleting.
     Reload and try again." and no counts in `extra`.
5. logger.info("course_deleted", course_id=course_id, name=name)
```

- **Why Core, not `db.delete(course)`:** the ORM acts on `Course`'s relationships before
  it deletes. `Course.games` has no cascade, so the ORM would set `course_id = NULL` on any
  game added in the race window and the delete would succeed, quietly unassigning that game
  instead of raising the `IntegrityError` this step relies on. A Core `DELETE FROM courses
  WHERE id = ?` skips the ORM, so the database alone applies its FKs: games and sessions
  block (no `ondelete`), roster and access rows cascade, images are set NULL. The ORM-only
  `cascade="all, delete-orphan"` on `Course.roster` / `Course.user_access` is not needed;
  the database cascades do the same job.
- The `course` object loaded in step 1 still sits in the session after the delete. That is
  harmless because the handler returns right away (`expire_on_commit=False`).
- Imports: `Course` (`models/course.py`), `Game` (`models/game.py`), `GameSession`
  (`models/session.py`), `Image` (`models/image.py`); `delete` from `sqlalchemy`;
  `IntegrityError` from `sqlalchemy.exc`.
- The message is the important part: the admin API client (`frontend/admin/src/lib`) only
  surfaces `message`, so the counts must be in the text. `extra` is for tests and future
  clients.
- No schema changes (no request body; 204 has no response model). No migration.

### 4.2 Admin UI: `frontend/admin/src/pages/CoursesPage.tsx`

- Each course row gets a **Delete** button (`Button` `variant="destructive"`, `size` matching
  the row's other buttons), after the existing row actions.
- Handler, following `GamesPage.deleteGame`:
  ```
  deleteCourse(c):
    if !confirm(`Delete "${c.name} — ${c.semester}"? Its roster and host/player access
                 are deleted too. This cannot be undone.`) return
    setError('')
    try: api.delete(`/admin/courses/${c.id}`); remove c from the list state
    catch err: setError(err.message, else 'Failed to delete course')
  ```
- The page already has `error` state and its error line (`text-danger-fg`); reuse them.
- No other page changes. Other pages load courses fresh on mount, so a deleted course just
  stops appearing.
- Theme: only existing tokens/primitives; run `python scripts/check_theme.py` before the MR.

### 4.3 Test teardown

- **`tests/integration/conftest.py` `game_setup`:** after the existing
  `DELETE /api/admin/games/{game_id}`, add `DELETE /api/admin/courses/{course_id}` with the
  same headers and timeout, result ignored (teardown never fails a test). Replace the comment
  "Courses have no cascade and no DELETE endpoint; leave them as inert records." with one
  saying the course is deleted last, after its game.
- **`tests/integration/t4_helpers.py` `T4World`:**
  - add `self._courses: list[int]`; `course()` appends the new id;
  - add `track_course(course_id)` (like `track_game` / `track_image`);
  - `cleanup()` deletes courses **last**, after users:
    `DELETE /admin/courses/{id}` for each, result ignored. Order: sessions → games → images
    → users → courses;
  - update the module docstring's teardown list (add step 5) and remove "Courses and roster
    rows are left as inert records (no course-delete endpoint)". Roster rows go with the
    course now.
- **`tests/integration/test_host_management.py`** (~line 192) creates a course directly
  ("T4 Course <tag>ng", `allow_guests: False`); call `t4.track_course(...)` on its id. This
  is the only `POST /admin/courses` in `tests/` besides the two helpers above.
- Out of scope: `scripts/seed_demo.py` (demo data, meant to stay) and
  `scripts/smoke_test_websocket.py` also create courses; neither is changed here.
- Known leftovers, accepted: a course still leaks if a test dies before teardown, or if a
  test left something the teardown doesn't track (for example image copies made by a game
  move into another course). The course delete then gets a 409, which teardown ignores.
  `scripts/prune_test_courses.py` still cleans those.

### 4.4 New tests: `tests/integration/test_course_delete.py`

Use the `t4` fixture and its helpers (`t4.course`, `t4.game`, `t4.user`, `t4.grant_course`,
`play_game`, `upload`, `assert_error`).

| # | Setup | Call | Expect |
|---|---|---|---|
| 1 | empty course | admin DELETE | 204; `GET /admin/courses/{id}` → 404; not in `GET /admin/courses` |
| 2 | course + 2 roster rows (`POST /admin/courses/{id}/roster/import`) + one user granted HOST (`t4.grant_course`) | admin DELETE | 204; that user's `GET /game/my-courses` no longer lists it; `GET /admin/courses/{id}/roster` → 404 |
| 3 | course + one game (`t4.game(course)`) | admin DELETE | 409 `COURSE_NOT_EMPTY`; body `games == 1, sessions == 0, images == 0`; course still `GET`-able |
| 4 | course A + game, `play_game(... finish=True)` (a COMPLETED session in A), then `POST /admin/games/{gid}/move {course_id: B, confirm: true}` | admin DELETE A | 409; `games == 0, sessions == 1` |
| 5 | course + one image (`upload(t4, png(), course_id=course)`, tracked) | admin DELETE | 409; `images == 1` |
| 6 | case 3, then delete the game (`DELETE /admin/games/{gid}`) | admin DELETE | 204 (sessions removed by the game delete, so the course is empty) |
| 7 | empty course | DELETE as a HOST of that course (`t4.user()` + `grant_course`) | 403; course still exists |
| 8 | — | admin DELETE `/admin/courses/999999999` | 404 |
| 9 | empty course | DELETE with no token | 401 |

Each test tracks what it creates, so teardown cleans up (`t4.track_course` for courses it
deletes itself is harmless: teardown's DELETE just gets 404).

Run the suite against the live stack (`pytest tests/integration`), and confirm with
`python scripts/prune_test_courses.py` (dry run) that a full run leaves no new "Test Course" /
"T4 Course" rows.

### 4.5 Docs

- `backend/app/routers/CLAUDE.md`: endpoint count for `admin.py` (38 → 39); list
  `DELETE /admin/courses/{id}` with its 409 rule; in Gotchas, drop "a course" from "There is no
  endpoint to delete a course, a roster entry …".
- `backend/app/models/CLAUDE.md` Gotchas: replace "(there is no course-delete endpoint)" with
  a pointer to the endpoint's refuse-if-not-empty rule.
- `frontend/admin/src/pages/CLAUDE.md` (`CoursesPage`) and `frontend/admin/src/lib/CLAUDE.md`
  (endpoint table row: add `DELETE /admin/courses/{id}`); `frontend/admin/src/components/CLAUDE.md`
  (add `CoursesPage` to the list of pages using `window.confirm()`).
- `scripts/prune_test_courses.py` docstring: say the tests now delete their courses, and the
  script is for leftovers from before this change or from crashed runs.

## 5. Open questions / risks

- **A played course can never be deleted.** By design (see §3). If admins later need to remove
  old semesters, that is a separate archive or export-then-delete feature.
- **Race with concurrent creates.** Covered by the IntegrityError → 409 path for games and
  sessions (their FKs have no `ondelete`, so MySQL blocks the delete). This only holds
  because the delete is a Core statement (§4.1); an ORM delete would unassign a racing game
  instead. Not covered by a test (the window can't be hit reliably). An **image** uploaded
  into the course in that window is not caught: its FK is `ON DELETE SET NULL`, so it
  silently becomes courseless (visible under the admin Images page's "unassigned" filter).
  Accepted as very unlikely for an admin-only action.
