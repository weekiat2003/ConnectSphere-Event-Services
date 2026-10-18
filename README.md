# ConnectSphere-Event-Services

## Project layout

```
connectsphere/
├── backend/        # Flask REST API
├── frontend/       # Vue 3 + Vite single-page app
├── database/
│   └── schema.sql  # MySQL DDL — run this once to create the database
└── .gitignore
```

## Prerequisites

- Python 3.11+
- Node.js 18+ and npm
- MySQL 8.0+
- (Optional) `virtualenv` for isolating Python dependencies

## 1. Database setup

1. Create the database and a user for it:

   ```sql
   CREATE DATABASE connectsphere CHARACTER SET utf8mb4;
   CREATE USER 'connectsphere_user'@'localhost' IDENTIFIED BY 'password';
   GRANT ALL PRIVILEGES ON connectsphere.* TO 'connectsphere_user'@'localhost';
   FLUSH PRIVILEGES;
   ```

2. Load the schema:

   ```bash
   mysql -u connectsphere_user -p connectsphere < database/schema.sql
   ```

   This creates all tables and seeds the five fixed roles (`event_organiser`,
   `event_coordinator`, `venue_staff`, `technical_support_staff`,
   `attendee`).

## 2. Backend setup (Flask API)

```bash
cd backend
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: set DATABASE_URL to match the DB user/password you created above
```

Since ConnectSphere accounts are provisioned outside the system (Event
Organisers, Attendees) or created directly by ConnectSphere (internal
staff), there is no self-registration endpoint yet. Seed a set of test
users for local development instead:

```bash
python scripts/seed_users.py
```

This creates one user per role (`organiser@example.com`,
`coordinator1@example.com`, `coordinator2@example.com`, `venue@example.com`,
`techsupport@example.com`, `attendee@example.com`), all with the password
`Password123!`.

The seed script also creates a varied venue catalogue for search testing, with
room layouts such as `theatre`, `classroom`, `u-shape`, `banquet`, `boardroom`,
`cabaret`, `hollow square`, `island`, and `standing`. The Room layout filter
offers the distinct layouts recorded for active venues; these are catalogue
labels, not a separate fixed list. Existing seeded venues are enriched with
missing sample catalogue values when the script is re-run, without removing
values maintained by Venue Staff.

Venue Staff can add or edit venue locations, layouts, facilities, accessibility
features, and capacities in the Venue Catalogue. Search-filter options are
derived from active venues, so staff changes are reflected by the next options
request; layouts are not limited to the sample values in the seed script.

For a fresh database, `database/schema.sql` creates the complete schema,
including the `venue_layouts` table. To replace an older local development
database, back up any data you need, drop the old `connectsphere` database,
then run the schema command above and seed it again. Do not drop a database
containing data you need to keep.

Run the API:

```bash
python run.py
```

The API listens on `http://localhost:5000/api`.

### Running tests

```bash
pip install pytest
pytest
```

### CI/CD pipeline

`.github/workflows/pipeline.yml` runs on every pull request into `main` and
every push to `main`:

| Job | What it checks or does | Runs on |
|---|---|---|
| `lint` | Ruff (rules in `ruff.toml`) | every PR and push |
| `test` | Backend unit and integration tests (pytest) | every PR and push |
| `audit` | `pip-audit` on backend deps, `npm audit` on shipped frontend deps | every PR and push |
| `package` | Builds `connectsphere-release.zip` once (backend + deps, built frontend, schema) and an SBOM | every PR and push |
| `smoke` | Runs the zip against MySQL and probes it with `smoke.sh` | every PR and push |
| `e2e` | Runs the zip and tests the login journey in a real browser (`e2e/`) | every PR and push |
| `staging` | Records the release's SHA-256 (placeholder, no deployment) | push to `main` |
| `production` | Waits for approval, then confirms it got the same zip (placeholder) | push to `main` |

Mark `test`, `smoke` and `e2e` (optionally `lint` and `audit`) as required
status checks on `main`. Add yourself as a required reviewer on the
`production` environment to make the release gate a human decision.

Run the smoke and browser tests locally against a running app:

```bash
bash smoke.sh http://localhost:5000                   # needs curl and jq; seeded DB
pip install playwright && python -m playwright install chromium
BASE_URL=http://localhost:5173/ python -m unittest discover -s e2e -v
```

## 3. Frontend setup (Vue)

```bash
cd frontend
npm install
cp .env.example .env
# edit .env if your backend isn't on http://localhost:5000/api
npm run dev
```

The app is served at `http://localhost:5173`. Log in with any of the seeded
test accounts above.

## 4. Typical local workflow

1. Start MySQL and confirm the schema is loaded.
2. In one terminal: `cd backend && source venv/bin/activate && python run.py`
3. In another terminal: `cd frontend && npm run dev`
4. Open `http://localhost:5173`, log in as `organiser@example.com` to create
   and submit an event request, then log in as `coordinator1@example.com` (or
   `coordinator2@example.com`, whichever the system auto-assigned) to review,
   request clarification, approve, or reject it.
