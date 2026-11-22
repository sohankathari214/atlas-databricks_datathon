# Atlas | A Virtue Foundation Tool

[Open the private Databricks app](https://find-the-right-care-7474644172043202.aws.databricksapps.com) · [Open the ranking notebook](https://dbc-069c8426-ea2f.cloud.databricks.com/editor/notebooks/13803159949638?o=7474644172043202)

Atlas compares nearby health facilities in India using the Virtue Foundation dataset and reviewed evidence. Enter a city, district and state, PIN, or coordinates and describe the care you need. The results show which facility claims matched, which sources support them, and which location or service conflicts affect the ranking. Avoid entering names and other identifying details in care descriptions.

## From browser request to Databricks

1. The web UI sends a location and care description to `POST /api/referral` on the Node.js backend. [Web UI](web/app.js) · [HTTP server](backend/server.mjs)
2. The backend loads the Unity Catalog service catalog and uses OpenAI to classify free text into a supported service. The catalog covers seven specific services, emergency departments, and general outpatient assessment. [Service catalog SQL](databricks/referral_service_catalog.sql) · [Care intake](backend/care-intake.mjs)
3. The backend binds the location and service as SQL parameters, sends the statement to `POST /api/2.0/sql/statements`, and polls the warehouse while the statement is pending or running. It uses the managed service principal in Databricks Apps or a Databricks CLI profile locally. [Referral queries](backend/referrals.mjs) · [Databricks client](backend/databricks.mjs)
4. Databricks resolves the search origin, finds facility claims within 100 km, joins reviewed evidence, and ranks the results. The backend returns the warehouse result to the browser with the matched service and keywords. [Referral search SQL](databricks/referral_search.sql)


## Evidence-based ranking and evaluation

Run [saboot_02_rank.py](databricks/saboot_02_rank.py) on Databricks Free Edition serverless. It describes the input tables, validates and matches gold labels, builds service features, fits a Bayesian model and checks calibration by district, then writes Delta outputs to `workspace.saboot`. The [SQL serving function](databricks/rank_referrals.sql) uses the resulting table for live ETC and phone-call recommendations. Apply its SQL after the notebook creates the tables and grant the app principal `USE SCHEMA` on `workspace.saboot` and `EXECUTE` on the function. Exact care terms can use the catalog immediately. Other free text uses the intake model.

Use `/Volumes/workspace/saboot/gold_inputs` for the following CSVs:

| File | Columns |
| --- | --- |
| `gold_manual.csv` | facility_id, service, y, method, source_url, labeller, date |
| `pmndp*.csv` | name, district, state, pin, phone, source_url, date |
| `nhm_fru*.csv` | name, district, state, pin, phone, source_url, date |
| `pmndp_complete_states.csv` (optional) | state, source_url, date, complete |

A service needs at least 30 independent positive labels and 30 independent negative labels with resolved districts and viable five-fold splits. The evaluation also needs at least 30 distinct held-out district origins with an eligible labelled positive. The notebook records audited registry-absence labels for review and excludes them from model fitting and evaluation because the absence rule itself uses a model feature. Websites used as gold label sources are removed from the evidence features. Geographic holdout models simulate travel from India Post district centroids to labelled candidates. Modelled minutes are distinct from observed patient journeys. The app identifies directory results when a service lacks a fitted model.

| Assumption | Default | Sensitivity grid | Purpose |
| --- | ---: | --- | --- |
| Detour factor `kappa` | 1.3 | 1.2, 1.4, 1.6 | Converts straight-line distance into an estimated road distance |
| Road speed `v` | 30 km/h | 20, 40 | Average speed proxy |
| Start overhead `t0` | 10 min | 0, 20 | Transport setup per modelled leg |
| Turn-away cost `h` | 30 min | 15, 60 | Time at a facility that cannot provide care |
| No-care penalty `H` | 240 min | 120, 480 | Time penalty for failing to obtain care |
| Call cost `c_call` | 3 min | 1, 10 | Minimum estimated gain for recommending a call |
| Prior shrinkage `m` | 10 | 5, 20 | Pulls small facility groups toward their service rate |

The travel grid uses three detour factors, three speeds (including 30), and three turn-away costs (including 30) for 27 runs per evaluable service. The other assumptions are varied individually. The fitted model card and `eval_tests` preserve the signs, confidence intervals, and p-values of the observed estimates.

The model card records current label coverage. The notebook prints the held-out search count, estimated minutes saved, 95% interval and p-value when evaluation is available.

## Enable free-text interpretation

Set `OPENAI_API_KEY` in the repository-root `.env` file. The local server loads it on startup. `OPENAI_MODEL` defaults to `gpt-6-luna`. The app uses the Responses API with Structured Outputs, reasoning set to none, and response storage disabled.

For the hosted app, transfer the key into its dedicated Databricks secret scope from a shell with an authenticated Databricks CLI:

```sh
npm run configure:llm
```

The command reads the ignored `.env` file, assigns the app's service principal read access to that scope, and transfers the key over the Databricks API. It does not print the key or deploy the file. The hosted app can pick up the secret on a subsequent search after a short cache interval. Until a key is configured, the app accepts exact catalog terms.

## Databricks workflow

The [live search notebook](databricks/Explore%20live%20referrals.py) accepts a location and service and queries the same functions as the app.

The directory fallback, `workspace.referral_verification.search_referrals`, resolves the location using documented city coordinates, Virtue city pins, or India Post locality, district and PIN data. It compares proximity-ranked mentions against service claim classifications, facility location flags, and eligible reviewed sources. If the name is ambiguous or missing from the lookup, enter a PIN or coordinates.

An explicit on-site mention provides a lead when model ranking is unavailable. Routine C-section, initial trauma stabilization, and an SNCU are shown with their narrower scope. Location conflicts have no distance or rank. Neither source volume nor a map listing establishes on-site care availability.

The root Databricks Apps configuration starts the backend and selects the SQL warehouse. After replacing the SQL function, reapply `EXECUTE` to the app service principal before redeploying because the warehouse may clear the grant on replacement. [Databricks Apps configuration](app.yaml)

## Source enrichment and review

The browser shows source links and reviewed signals. Collection runs separately through [enrichment.py](tools/enrichment.py) or the [Source research pipeline notebook](https://dbc-069c8426-ea2f.cloud.databricks.com/editor/notebooks/3477222532089481?o=7474644172043202). Set the number of workers and batch offset for the website collector. When Free Edition blocks outbound traffic to a provider, run the same collector externally, upload its JSONL to the research volume and choose **Import collected JSONL**. It produces leads requiring a campus match and review. Signed-in or CAPTCHA-protected directories can be collected by using an authorized export. Each CSV or HTML directory requires an explicit column map such as `{"name":"Hospital Name","address":"Address","pin":"Pin Code","phone":"Contact"}`.

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

## Facility contact and source refresh

The app offers a direct call link when the facility directory contains a usable public number. For a fitted service, Atlas may identify a call with the highest estimated value and suggest a question about capacity or availability.

Run the **Source research pipeline** to refresh records. For an operator-maintained list of specific web pages or PDFs, use `python3 tools/enrichment.py sources "$manifest"`. The CSV manifest accepts `publisher,url,source_type,facility_id,service,name,page,pattern`, where `pattern` is a text extraction regex and `page` is optional for PDFs. Import its JSONL through the notebook and review the source, exact campus and service before publication.
