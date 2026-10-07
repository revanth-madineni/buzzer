#!/usr/bin/env python3
"""
Delete leftover integration-test courses from the local dev database.

The integration tests create a course per run ("Test Course <tag>", "T4 Course <tag>",
"Slider E2E <tag>", ...) and there is no course-delete endpoint, so course pickers fill up
with hundreds of them. This removes a course only when BOTH hold:

  - its name matches one of the test-name patterns below, and
  - it has no games and no game sessions (so nothing real can be lost).

Its roster rows and access grants go with it (ON DELETE CASCADE), and so do its images:
a question may only use images from its own game's course, and these courses have no games.

Dry run by default; pass --apply to delete. Runs SQL through the mysql container with the
container's own credentials, so it needs the Docker stack up and nothing else.

Usage:
    python scripts/prune_test_courses.py           # show what would be deleted
    python scripts/prune_test_courses.py --apply   # delete it
"""

import argparse
import subprocess
import sys

NAME_PATTERN = r"^(Test Course |T[0-9]+ Course |Slider E2E |Smoke Test Course$)"

CANDIDATES = f"""
    SELECT c.id FROM courses c
    WHERE c.name REGEXP '{NAME_PATTERN}'
      AND NOT EXISTS (SELECT 1 FROM games g WHERE g.course_id = c.id)
      AND NOT EXISTS (SELECT 1 FROM game_sessions s WHERE s.course_id = c.id)
"""

REPORT = f"""
SELECT 'total courses', COUNT(*) FROM courses;
SELECT 'courses to delete', COUNT(*) FROM ({CANDIDATES}) x;
SELECT 'images to delete', COUNT(*) FROM images WHERE course_id IN ({CANDIDATES});
SELECT CONCAT('keep: #', id, ' ', name), '' FROM courses
    WHERE id NOT IN ({CANDIDATES}) ORDER BY id;
"""

APPLY = f"""
START TRANSACTION;
CREATE TEMPORARY TABLE prune_ids AS {CANDIDATES};
DELETE FROM images WHERE course_id IN (SELECT id FROM prune_ids);
DELETE FROM courses WHERE id IN (SELECT id FROM prune_ids);
SELECT 'deleted courses', ROW_COUNT();
COMMIT;
"""


def run_sql(sql: str) -> str:
    cmd = [
        "docker",
        "compose",
        "exec",
        "-T",
        "mysql",
        "sh",
        "-c",
        'mysql -N -B -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" 2>/dev/null',
    ]
    result = subprocess.run(cmd, input=sql, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"mysql failed (is the Docker stack up?)\n{result.stderr}")
    return result.stdout


def print_rows(out: str) -> None:
    for line in out.strip().splitlines():
        label, _, value = line.partition("\t")
        print(f"  {label} {value}".rstrip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    parser.add_argument(
        "--apply", action="store_true", help="delete (default: dry run)"
    )
    args = parser.parse_args()

    print_rows(run_sql(REPORT))
    if not args.apply:
        print("\nDry run; nothing deleted. Re-run with --apply to delete.")
        return
    print_rows(run_sql(APPLY))


if __name__ == "__main__":
    main()
