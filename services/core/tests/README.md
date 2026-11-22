# Submission and progress integration tests

Run from the repository root with Python 3.12+ and a disposable PostgreSQL database:

```powershell
python -m pip install -e './services/core[test]'
$env:TEST_DATABASE_URL = 'postgresql://postgres:postgres@127.0.0.1:55439/attempt_tests'
python -m pytest services/core/tests -q
```

Use only a local/test database. Each test creates a uniquely named schema, initializes
it with the production schema initializer, and drops it afterwards. The database
user needs CREATE SCHEMA permission. No production startup or backup loop runs.
Missing TEST_DATABASE_URL fails the tests rather than silently skipping them.

Requests use separate real PostgreSQL connections. A test-only connection adapter
pauses a request after its initial SELECT using threading Events; the other request
commits before the paused request resumes. There are no timing sleeps or mocked SQL.
Only the task grader and external live-backup writer are replaced. The backup spy
checks that both the accepted result and submit event are visible on another
connection, verifying that backup runs after commit. An event constraint failure
also verifies rollback of the result and suppression of backup.

`test_progress.py` exercises the real authenticated progress endpoint with saved
attempts, including zero, best-of-many, fractions, ungraded submissions, drafts,
hidden/deleted/reference tasks, missing sessions and user isolation. It also checks
that reads leave attempts unchanged and never invoke generators or create users.

Catalogue browser checks (API fixtures, no production data):

```powershell
cd apps/web
npm install
npx playwright install chromium
npm run test:browser
```

An installed Edge can be used instead with `$env:PLAYWRIGHT_CHANNEL = 'msedge'`.
Screenshots for both themes at 1280px and 375px are saved under `test-results/`.
Checks cover filtering, collapse, submission/return, loading/error/retry, zero and
empty results, mismatched user IDs, focus refresh, and delayed responses across
A → B → A session restoration.
