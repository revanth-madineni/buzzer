# Commit-after-response race in write handlers

Found while implementing T7 (map-pin) on `feat/t7-map-pin`, 2026-10-04. Fixed in commit
`7e9e197` ("Fix commit-after-response race in existing write handlers").

## The bug

`database.get_db` is a `yield` dependency that commits after the handler returns. On the
FastAPI version we run (0.142), `yield` dependencies are **request-scoped** by default: their
exit code, including that commit, runs *after the response has been sent*. So a client can
receive a 201/200/204 before the write is committed, and a request it sends right away can
read the old state.

Measured with a write-then-immediately-read loop against the dev stack, before the fix:

| write | stale reads |
|---|---|
| `POST /api/admin/courses/{id}/roster`, then list the roster | 24 / 40 |
| `POST /api/host/courses/{id}/games`, then `GET /api/host/games/{id}` | 10 / 40 |
| `POST /api/game/rooms`, then `GET /api/game/my-active-sessions` | 1 / 10 |
| `POST /api/admin/images`, then `GET /api/images/{id}` | 34 / 60 |

This is what made `tests/integration/test_host_management.py` intermittently fail. In the
app, the room case matters most: the host's socket `join_room` reads the new `GameSession`
from MySQL immediately after `POST /game/rooms` returns.

A second, quieter consequence: if the post-response commit fails, the client has already
been told the write succeeded.

## The fix (current)

Every write handler in `routers/admin.py`, `routers/host.py` and `routers/game.py` that
relied on `get_db` now calls `await db.commit()` itself, after its last write and before
returning. Handlers that already committed (e.g. admin create) were unchanged; read-only
handlers (`/auth/exchange-temp`, `/auth/refresh`) need nothing. After the fix the loop above
shows 0 stale reads.

Ordering matters: the commit must come **after** the write. Writing `await db.commit()`
before `return await service(...)` commits nothing useful and, on guarded question edits,
releases the `lock_game` row lock before the write runs.

**Rule for new handlers:** if a handler writes, commit before returning.

## Future improvement: `Depends(get_db, scope="function")`

The per-handler commit is easy to forget in a new handler. FastAPI 0.142 lets a `yield`
dependency run its exit code before the response is sent:

```python
DbSession = Annotated[AsyncSession, Depends(get_db, scope="function")]

async def handler(db: DbSession) -> ...: ...
```

Switching every handler to a shared `DbSession` annotation would:
- make the commit happen before the response everywhere, including future handlers;
- turn a failed commit into a 500 instead of a success the client already received;
- let the explicit `await db.commit()` calls be removed again.

Things to check when doing it:
- every handler signature changes (`Depends(get_db)` appears throughout `routers/`), so do it
  as its own change with the full integration suite;
- confirm exceptions raised in a handler still reach `get_db`'s `except` and roll back with
  function scope;
- check `get_db` users outside `routers/` (`common/dependencies.py`) take the same scope, so
  one request doesn't hold two sessions with different lifetimes.
