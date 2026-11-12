# EMRIS — Emergency Management & Resource Information System

EMRIS (Emergency Management & Resource Information System) is a web application to register, plan and track emergencies in Colombia. The project's goal is to combine day-to-day emergency management with machine learning on historical emergency data.

## Current features

- User registration and login
- Role-based access: `administrator`, `risk_manager`, `operator`, `action_owner`
- User management page where administrators assign roles
- Municipality catalog based on the DANE DIVIPOLA codes, with search, registration of missing municipalities by operators and validation by risk managers
- Emergency type catalog managed by administrators and risk managers
- Cleaned UNGRD emergency history (2025), with the response actions extracted from the free-text comments
- SGC seismicity catalog (magnitude 2.5 and above) linked to municipalities
- Emergencies: report, edit, list with filters and detail page
- Impact recorded with 10 variables per emergency
- Follow-up with the status flow `Reported → In response → Controlled → Closed`: a controlled emergency can return to in response, closing requires a recorded impact, and closed emergencies are read-only
- Action plans (one per emergency): operators draft them and administrators and risk managers approve them; each plan has actions with owners, due dates and statuses
- Resource catalog with stock; the resources assigned to an emergency are freed when it closes
- Earthquake link to the official SGC event: suggested on the emergency page and confirmed by the user; magnitude and depth are entered manually when there is no match
- Health check endpoint at `/health/`
- Deployment on Render with a Supabase PostgreSQL database

## Roles

| Role | Permissions |
|---|---|
| `administrator` | Everything: users, catalogs, resources, emergencies, closing emergencies and approving plans |
| `risk_manager` | Catalogs, resources, emergencies, closing emergencies and approving plans |
| `operator` | Reports and edits emergencies, records impact and follow-up, drafts plans, updates any action and registers municipalities (pending validation) |
| `action_owner` | Sees only the emergencies where they own an action and updates their own actions |

Users without a role wait for an administrator to assign one.

## Machine learning

Four components, trained on the 2025 UNGRD history. The impact estimator and similar emergencies are evaluated with a time-based split: train on January–September, test on October–December. Emergency profiles and municipal risk are fitted and scored on the whole year. The components live in the `ml/` package, which has no Django dependency, and are not yet connected to the web application.

| Component | Technique | Evaluation |
|---|---|---|
| Impact estimator | Supervised classification of high-impact emergencies using only fields known at report time (event type, department, municipality, month). Logistic regression and gradient boosting are compared; the decision threshold is tuned on September. | Logistic regression selected: F1 0.51 (recall 0.77, precision 0.38, PR-AUC 0.54). Baseline "same type and municipality": F1 0.48 (PR-AUC 0.41). Gradient boosting: F1 0.50. |
| Emergency profiles | K-means on log-scaled impact variables; emergencies with no recorded impact are labeled separately. | K = 3 chosen by silhouette (0.51), stable across seeds (ARI 0.98): "Minor impact", "Families affected and people affected", "Injuries and deaths". |
| Similar emergencies and suggested plan | k-nearest neighbors (k = 5) on type, place, month and impact. Suggested actions are those present in at least 2 of the 5 neighbors. | Precision@5 (same type and impact level): 0.94 with impact data, 0.78 without. Baseline, random neighbors of the same type: 0.75. |
| Municipal risk | Hierarchical agglomerative clustering (Ward) of municipalities with at least 3 emergencies, using emergency count, share of the three main types, share of high impact, mean impact and shallow seismic activity (M ≥ 4, depth < 70 km, within 50 km, from the SGC catalog). | K = 3 chosen by silhouette (0.21) and dendrogram, stability ARI 0.73. 620 municipalities ranked, 319 with insufficient history. Deep earthquakes of the Bucaramanga nest are excluded, so they do not raise Santander's level. |

## Notebooks

Five notebooks document the exploration and the models:

1. `01_exploration.ipynb`
2. `02_impact_estimator.ipynb`
3. `03_emergency_profiles.ipynb`
4. `04_similar_emergencies.ipynb`
5. `05_municipal_risk.ipynb`

```bash
pip install -r requirements-notebooks.txt
jupyter notebook notebooks/
```

Notebook outputs are cleared before committing. The notebook tools are not needed to run the application or the tests.

## Stack

- Python 3.12, Django 5.2
- pandas and scikit-learn for the machine learning components
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
