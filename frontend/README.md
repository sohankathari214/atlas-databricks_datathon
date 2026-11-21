# Find the right care

[Open the private Databricks app](https://find-the-right-care-7474644172043202.aws.databricksapps.com) · [Open the submission notebook](https://dbc-069c8426-ea2f.cloud.databricks.com/editor/notebooks/48725305901297?o=7474644172043202)

Enter an Indian city, district and state, PIN, or coordinates. Type a short description such as “looking for a dialysis appointment” or “need a hospital that performs coronary bypass.” GPT-6 Luna interprets the text against the Databricks service catalog and returns a service and canonical keywords. The location goes directly to Databricks. Avoid entering names and other identifying details in care descriptions.

The catalog includes emergency department and general outpatient assessment alongside the seven specific services. Symptom descriptions map to a care setting. If no specific service is supported, a non-emergency concern can start with general outpatient assessment. Common emergency phrases show guidance immediately and route to emergency department listings. These listings remain secondary and do not verify emergency or cardiac capability. Databricks handles facility retrieval and ranking after classification. After a search, the form shows the matched service and associated keywords below the care field.

## Enable free-text interpretation

Set `OPENAI_API_KEY` in the repository-root `.env` file. The local server loads it on startup. `OPENAI_MODEL` defaults to `gpt-6-luna`. The app uses the Responses API with Structured Outputs, reasoning set to none, and response storage disabled.

For the hosted app, transfer the key into its dedicated Databricks secret scope from a shell with an authenticated Databricks CLI:

```sh
cd frontend
npm run configure:llm
```

The command reads the ignored `.env` file, assigns the app's service principal read access to that scope, and transfers the key over the Databricks API. It does not print the key or deploy the file. The hosted app can pick up the secret on a subsequent search after a short cache interval. Until a key is configured, the app accepts exact catalog terms.

## Databricks workflow

Each search issues a parameterized SQL Statement Execution API request to the existing Serverless Starter Warehouse. General searches first read the supported intents from `workspace.referral_verification.referral_service_catalog()`. The classified service ID and location then go to the Unity Catalog `workspace.referral_verification.search_referrals` table function. It resolves the origin from documented city coordinates, Virtue city pins, or India Post locality, district and PIN data. It compares proximity-ranked mentions against the existing seven-service claim classification, facility location flags, and eligible reviewed sources. The radius is 100 km straight-line. If the name is ambiguous or missing from the lookup, enter a PIN or coordinates instead.

Outside curated cases, an explicit on-site mention is a lead. Routine C-section, initial trauma stabilization, and an SNCU are shown with their narrower scope. Location conflicts have no distance or rank. Neither source volume nor a map listing establishes on-site care availability.

The submission notebook can replay the original reviewed scenarios from `frontend_scenarios`, prepared by the publisher notebook. The submission folder includes the shared query, a widget notebook, website seed export, and reviewed evidence intake. After replacing the SQL function, reapply `EXECUTE` to the app service principal before redeploying because the warehouse may clear the grant on replacement.

## Source enrichment proof of concept

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

Configure `BRAVE_SEARCH_API_KEY` and `GOOGLE_PLACES_API_KEY` in the operator environment if needed. Neither integration runs during referral searches. The adapters do not assume free quotas or enable billing. This demo does not schedule the 8,400-site crawl or thousands of Google requests.

For each attributable lead, review the exact source and campus, set its Virtue facility ID and a substantive rationale, and set `review_status` to `reviewed`. Upload JSONL to an existing Unity Catalog volume. Run **Load reviewed referral evidence** in Validate mode, then Apply. Valid rows merge into `frontend_source_signals` and appear under applicable live facility results. Unknown facility IDs, missing rationale and Google records are excluded.

## Run locally

```sh
databricks auth login --host https://dbc-069c8426-ea2f.cloud.databricks.com --profile virtue-datathon
cd frontend
DATABRICKS_PROFILE=virtue-datathon npm start
```

Open [the local preview](http://127.0.0.1:4173). Set `DATABRICKS_CLI` to the binary path if it is outside your executable search path. The deployed app uses a Databricks-managed service principal and remains private.
