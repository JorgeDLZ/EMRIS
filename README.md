# EMRIS — Emergency Management & Resource Information System

EMRIS (Emergency Management & Resource Information System) is a web application to register, plan and track emergencies in Colombia. The project's goal is to combine day-to-day emergency management with machine learning on historical emergency data.

## Current features

- User registration and login
- Role-based access: `administrator`, `risk_manager`, `operator`, `action_owner`
- User management page where administrators assign roles
- Municipality catalog based on the DANE DIVIPOLA codes, with search, registration of missing municipalities by operators and validation by risk managers
- Emergency type catalog managed by administrators and risk managers
- Cleaned UNGRD emergency history (2025), with the response actions extracted from the free-text comments
- SGC seismicity catalog (magnitude 2.5 and above) linked to municipalities, with a rule that links an earthquake to an emergency
- Health check endpoint at `/health/`
- Deployment on Render with a Supabase PostgreSQL database

**Planned:** four machine learning components — impact estimator, emergency profiles, similar emergencies with a suggested action plan, and municipal risk profile.

## Stack

- Python 3.12, Django 5.2
- PostgreSQL on Supabase (database only); SQLite for local development
- WhiteNoise for static files, Gunicorn as the application server
- Render for hosting, GitHub Actions for continuous integration

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

For local development set `DEBUG=True` in `.env`. Without `DATABASE_URL`, a local SQLite database (`db.sqlite3`) is used.

## Data

The UNGRD file in `data/` is kept exactly as downloaded. The other two are derived from official sources:

| File | Source |
|---|---|
| `ungrd_emergencies_v2.csv` | "Emergencias UNGRD V2" open dataset from Datos Abiertos Colombia (UNGRD), exactly as downloaded |
| `divipola_dane.csv` | DANE DIVIPOLA municipality codes, extracted from the official DANE list |
| `sgc_seismicity_m25.csv` | Servicio Geológico Colombiano seismicity catalog, 2020-06-01 to 2026-11-07, filtered to magnitude 2.5 and above with rows unchanged |

Load them after migrating, in this order:

```bash
python manage.py migrate
python manage.py load_baseline
python manage.py load_seismic
```

- `load_baseline` loads the municipalities, the emergency type catalog and the cleaned UNGRD history.
- `load_seismic` loads the seismicity catalog and links each event to a municipality, so it needs the municipalities from `load_baseline`.
- Both commands are idempotent: running them again does not duplicate data.
- These commands write to whatever database `DATABASE_URL` points at, including Supabase in production. The free Render service has no shell, so the first load is run from a local machine with `DATABASE_URL` set to the Supabase pooler URL.

## Running tests

```bash
python -m pytest
```

## Environment variables

| Variable | Description |
|---|---|
| `SECRET_KEY` | Django secret key. Required when `DEBUG` is off. |
| `DEBUG` | `True` for local development, `False` in production. |
| `ALLOWED_HOSTS` | Comma-separated list of allowed host names. |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated list of trusted origins, including the scheme (for example `https://emris.onrender.com`). |
| `DATABASE_URL` | PostgreSQL connection URL. Defaults to local SQLite when unset. |

## Deployment on Render

1. Push the repository to GitHub.
2. In Render, create a new Blueprint from the repository; `render.yaml` defines the `emris` web service.
3. Set `DATABASE_URL` to the Supabase shared pooler URL in session mode (port 5432). Render cannot reach Supabase's IPv6-only direct connection, so the pooler URL is required.
4. Set `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` if they are not covered by the Render hostname.
5. The build runs `build.sh` (install dependencies, collect static files, apply migrations). Render checks `/health/` to confirm the service is up.

## First administrator

Run `python manage.py createsuperuser` against the production database (with `DATABASE_URL` pointing to Supabase). A superuser has full access. Additional users register themselves and have no access until an administrator assigns a role from the Users page.

## Manual backup

```bash
pg_dump "$DATABASE_URL" --no-owner --format=custom --file=emris-$(date +%F).dump
```
