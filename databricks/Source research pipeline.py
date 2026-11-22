# Databricks notebook source
# MAGIC %md
# MAGIC # Source research pipeline
# MAGIC Run bounded source adapters that collect evidence leads for review. Records remain marked `lead` and do not enter the live facility ranking until a reviewer confirms source, campus, and claim.
# MAGIC
# MAGIC Sources include official hospital websites, data.gov.in hospital/public health facility/blood bank exports, PM-JAY, state dialysis program lists, emergency obstetric referral unit lists, NABH, OpenStreetMap, Overture, Google Places, Brave news/tenders/jobs, and public review exports.
# MAGIC
# MAGIC The official website collector checks robots.txt and crawl delay, then reads a homepage and up to ten same-host service pages for each selected facility. The challenge estimate is 8,400 sites and 2–3 hours. Run small batches first. Collection runtime depends on host rules and response time.
# MAGIC
# MAGIC Google Places results are temporary operator lookups. Do not store Google Places content in the facility evidence table. Maps status and map datasets describe location/existence, not service capability. Reviews and job adverts are anecdotal or contextual leads.
# MAGIC
# MAGIC Use authorized public exports where a source blocks access. The adapters do not bypass robots rules, accounts, CAPTCHA, or paywalls.

# COMMAND ----------

dbutils.widgets.dropdown('source', 'Official hospital websites', [
    'Official hospital websites', 'Hospital directory · data.gov.in', 'Public facilities · data.gov.in',
    'Blood banks · data.gov.in', 'PM-JAY hospital finder', 'State free dialysis centres',
    'Emergency obstetric referral units', 'NABH accreditation', 'OpenStreetMap', 'Overture',
    'Google Places location check', 'Brave news, tenders and jobs', 'Find public reviews', 'Public reviews or Facebook export',
    'Review staged leads', 'Import collected JSONL', 'Google Places status'
], 'Source')
dbutils.widgets.text('batch_size', '3', 'Facilities per batch')
dbutils.widgets.text('batch_offset', '0', 'Start after this many facility seeds')
dbutils.widgets.text('crawl_workers', '4', 'Parallel website hosts (1–24)')
dbutils.widgets.text('secret_scope', 'referral-research', 'Databricks API secret scope')
dbutils.widgets.text('service', 'dialysis', 'Service')
dbutils.widgets.text('source_input', '', 'CSV, HTML, GeoJSON or seed CSV path')
dbutils.widgets.text('source_landing_url', '', 'Public source landing URL')
dbutils.widgets.text('publisher', '', 'Source publisher')
dbutils.widgets.text('column_map', '{}', 'Source column mapping JSON')
dbutils.widgets.text('google_secret_key', '', 'Google API secret key name')
dbutils.widgets.text('brave_secret_key', '', 'Brave API secret key name')
dbutils.widgets.dropdown('run_collection', 'No', ['No', 'Yes'], 'Confirm external collection')
dbutils.widgets.dropdown('review_mode', 'Leads only', ['Leads only', 'Merge approved reviews'], 'Review action')

# COMMAND ----------

import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from pyspark.sql import functions as F

CATALOG = 'databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities'
SCHEMA = 'workspace.referral_verification'
LEADS = SCHEMA + '.external_research_leads'
REVIEWED = SCHEMA + '.frontend_source_signals'
VOLUME = '/Volumes/workspace/referral_verification/research'

spark.sql('CREATE SCHEMA IF NOT EXISTS ' + SCHEMA)
spark.sql(f'''CREATE TABLE IF NOT EXISTS {LEADS} (
  lead_id STRING, facility_id STRING, service STRING, source_type STRING, publisher STRING, url STRING,
  checked DATE, event DATE, published DATE, excerpt STRING, rationale STRING, review_status STRING,
  name STRING, place STRING, address STRING, pin STRING, phone STRING, latitude DOUBLE, longitude DOUBLE,
  operating_status STRING, existence_confidence DOUBLE, map_id STRING, attribution STRING
) USING DELTA COMMENT 'External research leads. Unreviewed records do not affect referral search.' ''')

source = dbutils.widgets.get('source')
if source == 'Review staged leads':
    display(spark.table(LEADS).orderBy(F.col('checked').desc_nulls_last()).limit(250))
else:
    if dbutils.widgets.get('review_mode') == 'Merge approved reviews':
        reviewed = spark.table(LEADS).where("review_status = 'reviewed'")
        valid_ids = spark.table(CATALOG).select(F.col('unique_id').alias('facility_id')).distinct()
        accepted = reviewed.join(valid_ids, 'facility_id', 'left_semi').where(
            F.col('source_type').isin('hospital_website','hospital_directory','public_facilities','blood_banks',
              'pmjay','pmndp','obstetric_fru','nabh','OpenStreetMap','Overture','web_search','review','news_report','hospital_page')
            & F.col('url').rlike(r'^https?://') & F.length(F.trim('rationale')).gt(0)
        )
        accepted.createOrReplaceTempView('approved_external_leads')
        spark.sql(f'''MERGE INTO {REVIEWED} AS target USING approved_external_leads AS source
          ON target.signal_id=source.lead_id
          WHEN MATCHED AND source.checked >= target.checked THEN UPDATE SET
            target.facility_id=source.facility_id,target.service=source.service,target.source_type=source.source_type,
            target.publisher=source.publisher,target.url=source.url,target.checked=source.checked,
            target.event=source.event,target.published=source.published,target.excerpt=source.excerpt,
            target.rationale=source.rationale,target.review_status='reviewed'
          WHEN NOT MATCHED THEN INSERT
            (signal_id,facility_id,service,source_type,publisher,url,checked,event,published,excerpt,rationale,review_status)
            VALUES (source.lead_id,source.facility_id,source.service,source.source_type,source.publisher,
              source.url,source.checked,source.event,source.published,source.excerpt,source.rationale,'reviewed')''')
        display(accepted.limit(100))
    elif dbutils.widgets.get('run_collection') != 'Yes':
        print('Choose a source and set Confirm external collection to Yes to run a collector. No network requests were made.')
    else:
        volume_dir = Path(VOLUME)
        if not volume_dir.is_dir():
            raise ValueError(f'Create the Unity Catalog volume {VOLUME}, then upload tools/enrichment.py there.')
        adapter = str(volume_dir / 'enrichment.py')
        batch = int(dbutils.widgets.get('batch_size'))
        if not 1 <= batch <= 8400:
            raise ValueError('Batch size must be from 1 to 8,400 facilities.')
        input_path = dbutils.widgets.get('source_input').strip()
        landing = dbutils.widgets.get('source_landing_url').strip()
        publisher = dbutils.widgets.get('publisher').strip() or source
        env = os.environ.copy()
        scope = dbutils.widgets.get('secret_scope')
        temp = tempfile.TemporaryDirectory(prefix='atlas-collection-')
        argv = [sys.executable, adapter]
        source_types = {
          'Hospital directory · data.gov.in':'hospital_directory',
          'Public facilities · data.gov.in':'public_facilities', 'Blood banks · data.gov.in':'blood_banks',
          'PM-JAY hospital finder':'pmjay', 'State free dialysis centres':'pmndp',
          'Emergency obstetric referral units':'obstetric_fru','NABH accreditation':'nabh',
          'Public reviews or Facebook export':'review'
        }
        if source == 'Import collected JSONL':
            path = Path(input_path).resolve()
            if not path.is_relative_to(Path('/Volumes')) or path.suffix != '.jsonl':
                raise ValueError('Select a JSONL file under /Volumes/.')
        elif source == 'Official hospital websites':
            pages = 10
            offset = max(0, int(dbutils.widgets.get('batch_offset')))
            workers = int(dbutils.widgets.get('crawl_workers'))
            seeds = spark.sql(f'''SELECT unique_id facility_id,name,officialWebsite website,
              concat_ws(', ',address_city,address_stateOrRegion) place,
              concat_ws(', ',address_line1,address_line2,address_city,address_stateOrRegion,address_zipOrPostcode) address
              FROM {CATALOG} WHERE nullif(trim(officialWebsite),'') IS NOT NULL ORDER BY unique_id LIMIT {batch} OFFSET {offset}''')
            seed_file = str(Path(temp.name) / 'website_seeds.csv')
            pandas_seeds = seeds.toPandas()
            pandas_seeds.to_csv(seed_file,index=False,quoting=csv.QUOTE_MINIMAL)
            argv += ['crawl',seed_file,'--limit',str(batch),'--pages',str(pages),'--workers',str(workers)]
        elif source in source_types:
            if not input_path or not landing:
                raise ValueError('Provide the authorized source export and its public source landing URL.')
            mapping = json.loads(dbutils.widgets.get('column_map'))
            if not isinstance(mapping,dict): raise ValueError('Column mapping must be a JSON object.')
            mapping_file=str(Path(temp.name) / 'column_map.json')
            Path(mapping_file).write_text(json.dumps(mapping))
            argv += ['directory',input_path,'--source-type',source_types[source], '--publisher',publisher,
                     '--url',landing,'--columns',mapping_file]
        elif source in ('OpenStreetMap','Overture'):
            if not input_path or not landing: raise ValueError('Provide an attributable point GeoJSON extract and its source landing page.')
            argv += ['open-maps',input_path,'--provider',source,'--url',landing]
        elif source in ('Google Places location check','Google Places status'):
            if not input_path: raise ValueError('Provide a facility seed CSV or the operator-reviewed Place ID for status.')
            secret=dbutils.widgets.get('google_secret_key').strip()
            if not secret: raise ValueError('Provide the Google Places secret key name.')
            env['GOOGLE_PLACES_API_KEY']=dbutils.secrets.get(scope=scope,key=secret)
            argv += ['google-status',input_path] if source == 'Google Places status' else ['google-places',input_path,'--limit',str(min(batch,5000))]
        elif source in ('Brave news, tenders and jobs','Find public reviews'):
            if not input_path: raise ValueError('Provide a facility seed CSV with facility_id, name, address, and place columns.')
            secret=dbutils.widgets.get('brave_secret_key').strip()
            if not secret: raise ValueError('Provide the Brave Search secret key name.')
            env['BRAVE_SEARCH_API_KEY']=dbutils.secrets.get(scope=scope,key=secret)
            argv += ['brave',input_path,'--limit',str(batch),'--service',dbutils.widgets.get('service')]
            if source == 'Find public reviews':
                argv += ['--reviews']
        if source == 'Import collected JSONL':
            with path.open(encoding='utf-8') as content:
                records = [json.loads(line) for line in content if line.strip()]
        else:
            completed = subprocess.run(argv,capture_output=True,text=True,timeout=14400,env=env)
            if completed.returncode:
                raise RuntimeError('Collection adapter failed: '+completed.stderr[-2500:])
            if completed.stderr:
                print(completed.stderr[-2500:])
            records = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
        # Google Places terms prohibit storing returned Google content in facility research tables.
        if source in ('Google Places location check','Google Places status'):
            display(spark.createDataFrame(records) if records else spark.createDataFrame([], 'facility_id string, google_place_ids array<string>, maps_links array<string>'))
            print(f'{len(records)} operator-only location lookups. Results were not persisted.')
        else:
            normalized=[]
            allowed = {'hospital_website','hospital_directory','public_facilities','blood_banks','pmjay','pmndp',
                       'obstetric_fru','nabh','OpenStreetMap','Overture','web_search','review','news_report','hospital_page'}
            for record in records:
                if record.get('source_type') not in allowed:
                    continue
                record['review_status'] = 'lead'
                record.setdefault('checked',None)
                record.setdefault('facility_id',None)
                record.setdefault('service',None)
                record.setdefault('source_type',source if source in ('OpenStreetMap','Overture') else 'review' if source == 'Public reviews or Facebook export' else 'web_search')
                record.setdefault('publisher',publisher)
                record.setdefault('event',None)
                record.setdefault('published',None)
                record.setdefault('excerpt',None)
                record.setdefault('rationale','Source lead. Verify original source and exact campus before review.')
                record['lead_id']=hashlib.sha256('|'.join(str(record.get(k) or '') for k in
                  ('facility_id','service','source_type','url','excerpt','name','map_id')).encode()).hexdigest()
                normalized.append(record)
            if normalized:
                schema = spark.table(LEADS).schema
                columns = schema.fieldNames()
                def as_text(value):
                    return json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list)) else str(value) if value is not None else None
                frame = spark.createDataFrame([tuple(as_text(row.get(c)) for c in columns) for row in normalized],
                                              ', '.join(f'{c} string' for c in columns))
                frame = frame.select(*[F.expr(f'try_cast({field.name} as {field.dataType.simpleString()})').alias(field.name)
                                       for field in schema])
                frame = frame.where(F.col('url').rlike(r'^https?://') & F.col('checked').isNotNull()).dropDuplicates(['lead_id'])
                frame.createOrReplaceTempView('incoming_research_leads')
                spark.sql(f'''MERGE INTO {LEADS} target USING incoming_research_leads source ON target.lead_id=source.lead_id
                  WHEN MATCHED AND target.review_status='lead' THEN UPDATE SET *
                  WHEN NOT MATCHED THEN INSERT *''')
            temp.cleanup()
            display(spark.table(LEADS).where("review_status = 'lead'").orderBy(F.col('checked').desc_nulls_last()).limit(100))
            print(f'{len(normalized)} leads staged.')

# COMMAND ----------

# MAGIC %md
# MAGIC ## Source-specific interpretation
# MAGIC - Government lists show presence in a particular programme or directory, subject to its listing date and eligibility rules.
# MAGIC - Map records can help identify a place, its operating status and existence confidence. They do not verify a hospital service.
# MAGIC - News, tenders, vacancies and reviews are discovery signals. Open the original source and retain only a short contextual excerpt.
# MAGIC - Official website statements are self-reported. Review their exact campus, recency and service wording.
# MAGIC - Google Places status/content is for manual operator follow-up and is never merged into either table.
# MAGIC - Only reviewed records with a known Virtue facility ID, source URL, and reviewer rationale can be merged into the evidence table.
# MAGIC
# MAGIC ## Crawl scale
# MAGIC The challenge estimates 8,400 facilities. A single 8,400-site run with the maximum ten service pages per site can issue about 92,400 page requests. With one-second per-host delay alone this exceeds 25 hours serially across sites; the stated 2–3 hours requires parallel workers. Set a batch offset and run independent host groups in parallel. Use the same batch order to resume. When Free Edition blocks an external host, run the same adapter externally and import the collected JSONL through an authorized Unity Catalog volume.
