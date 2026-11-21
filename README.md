# Find the right care

[Open the private Databricks app](https://find-the-right-care-7474644172043202.aws.databricksapps.com) · [Open the submission notebook](https://dbc-069c8426-ea2f.cloud.databricks.com/editor/notebooks/48725305901297?o=7474644172043202)

Find the right care compares nearby health facilities in India using the Virtue Foundation dataset and reviewed evidence. Enter a city, district and state, PIN, or coordinates and describe the care you need. The results show which facility claims matched, which sources support them, and which location or service conflicts affect the ranking. Avoid entering names and other identifying details in care descriptions.

## From browser request to Databricks

1. The web UI sends a location and care description to `POST /api/referral` on the Node.js backend. [Web UI](web/app.js) · [HTTP server](backend/server.mjs)
2. The backend loads the Unity Catalog service catalog and uses OpenAI to classify free text into a supported service. The catalog covers seven specific services, emergency departments, and general outpatient assessment. [Service catalog SQL](databricks/referral_service_catalog.sql) · [Care intake](backend/care-intake.mjs)
3. The backend binds the location and service as SQL parameters, sends the statement to `POST /api/2.0/sql/statements`, and polls the warehouse while the statement is pending or running. It uses the managed service principal in Databricks Apps or a Databricks CLI profile locally. [Referral queries](backend/referrals.mjs) · [Databricks client](backend/databricks.mjs)
4. Databricks resolves the search origin, finds facility claims within 100 km, joins reviewed evidence, and ranks the results. The backend returns the warehouse result to the browser with the matched service and keywords. [Referral search SQL](databricks/referral_search.sql)

The submission notebook calls the same Unity Catalog function directly. It also supports the Palwal MRI and Bhagalpur dialysis scenarios prepared by the scenario publisher. [Submission notebook source](databricks/Explore%20live%20referrals.py) · [Scenario publisher](databricks/Publish%20referral%20frontend.py)

## Enable free-text interpretation

Set `OPENAI_API_KEY` in the repository-root `.env` file. The local server loads it on startup. `OPENAI_MODEL` defaults to `gpt-6-luna`. The app uses the Responses API with Structured Outputs, reasoning set to none, and response storage disabled.

For the hosted app, transfer the key into its dedicated Databricks secret scope from a shell with an authenticated Databricks CLI:

```sh
npm run configure:llm
```

The command reads the ignored `.env` file, assigns the app's service principal read access to that scope, and transfers the key over the Databricks API. It does not print the key or deploy the file. The hosted app can pick up the secret on a subsequent search after a short cache interval. Until a key is configured, the app accepts exact catalog terms.

## Databricks workflow

The `workspace.referral_verification.search_referrals` table function resolves the location using documented city coordinates, Virtue city pins, or India Post locality, district and PIN data. It compares proximity-ranked mentions against service claim classifications, facility location flags, and eligible reviewed sources. If the name is ambiguous or missing from the lookup, enter a PIN or coordinates.

Outside curated cases, an explicit on-site mention is a lead. Routine C-section, initial trauma stabilization, and an SNCU are shown with their narrower scope. Location conflicts have no distance or rank. Neither source volume nor a map listing establishes on-site care availability.

The root Databricks Apps configuration starts the backend and selects the SQL warehouse. After replacing the SQL function, reapply `EXECUTE` to the app service principal before redeploying because the warehouse may clear the grant on replacement. [Databricks Apps configuration](app.yaml)

## Source enrichment and review

The browser shows source links and reviewed signals. Collection runs separately through [enrichment.py](tools/enrichment.py). It produces leads requiring a campus match and review. Signed-in or CAPTCHA-protected directories can be collected by using an authorized export. Each CSV or HTML directory requires an explicit column map such as `{"name":"Hospital Name","address":"Address","pin":"Pin Code","phone":"Contact"}`.

| Source | Adapter and interpretation |
| --- | --- |
| Official websites | Export the Databricks crawl seeds, then crawl the homepage and up to ten same-host service links per campus with per-host pacing and robots checks. Keyword excerpts need context review. |
| data.gov.in hospital, public facility and blood bank lists | Load publisher CSV exports, or a direct public CSV URL allowed by robots rules. These are location and scope leads. |
| PM-JAY, state dialysis centres, emergency obstetric referral units and NABH | Parse a public HTML table or authorized CSV/HTML export. Listings establish participation, accreditation or documented scope. Eligibility and availability require confirmation. |
| OSM and Overture | Import attributable point GeoJSON from an extract. Overture's existence confidence and operating status describe the place. Preserve licensing and attribution when reviewing the export. |
| Google Places | Optional server-side operator command looks up Place IDs. Confirm a candidate's exact campus in Google Maps. The optional status command reads a selected ID for ephemeral operator review. Google Maps content stays outside the serving table. |
| Brave news, tenders and jobs | Optional limited search. Follow each result to its original document, record dates and scope, and distinguish plans or staffing from documented care. |
| Reviews | Open a public listing or the Virtue Facebook URL, or import a permitted review export. Record only the relevant non-identifying anecdotal signal. |

Examples for small batches:

```sh
python3 tools/enrichment.py crawl website-seeds.csv --limit 3 --pages 10 > leads.jsonl
python3 tools/enrichment.py directory hospitals.csv --source-type hospital_directory --publisher 'data.gov.in' --url '<publisher dataset URL>' --columns columns.json > registry-leads.jsonl
python3 tools/enrichment.py open-maps places.geojson --provider Overture --url 'https://docs.overturemaps.org/guides/places/' > map-leads.jsonl
python3 tools/enrichment.py brave website-seeds.csv --limit 2 --service dialysis > search-leads.jsonl
python3 tools/enrichment.py google-places website-seeds.csv --limit 2 > place-ids.jsonl
python3 tools/enrichment.py google-status '<reviewed Place ID>'
```

Configure `BRAVE_SEARCH_API_KEY` and `GOOGLE_PLACES_API_KEY` in the operator environment if needed. Operators run these adapters independently of referral searches.

For each attributable lead, review the exact source and campus, set its Virtue facility ID and a substantive rationale, and set `review_status` to `reviewed`. Upload JSONL to an existing Unity Catalog volume. Run **Load reviewed referral evidence** in Validate mode, then Apply. Valid rows merge into `frontend_source_signals` and appear under applicable live facility results. Unknown facility IDs, missing rationale and Google records are excluded.

## Run locally

Run these commands from the repository root with Node.js and the Databricks CLI installed.

```sh
databricks auth login --host https://dbc-069c8426-ea2f.cloud.databricks.com --profile virtue-datathon
DATABRICKS_PROFILE=virtue-datathon npm start
```

Open [the local preview](http://127.0.0.1:4173). Set `DATABRICKS_CLI` to the binary path if it is outside your executable search path. The deployed app uses a Databricks-managed service principal and remains private.

To retrieve warehouse results directly from the search endpoint, run this from another terminal.

```sh
curl --get http://127.0.0.1:4173/api/referral \
  --data-urlencode 'location=Jaipur, Rajasthan' \
  --data-urlencode 'service=c_section'
```
