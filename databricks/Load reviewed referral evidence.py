# Databricks notebook source
# MAGIC %md
# MAGIC # Load reviewed referral evidence
# MAGIC Upload newline-delimited JSON from the research adapters to a Unity Catalog volume. Review source, campus ID, date and scope. Record your match rationale, and change `review_status` to `reviewed` only once the specific campus is corroborated. A map, listing, review or job advertisement is context and does not verify a service. The import rejects unknown facility IDs and excludes Google Places content. Select **Validate** to inspect accepted rows before applying.

# COMMAND ----------

dbutils.widgets.text('input', '', 'UC volume path')
dbutils.widgets.dropdown('mode', 'Validate', ['Validate','Apply'], 'Action')

# COMMAND ----------

from pyspark.sql import functions as F

path = dbutils.widgets.get('input').strip()
if not path.startswith('/Volumes/'):
    raise ValueError('Enter a reviewed JSONL file or folder under /Volumes/.')

signals = spark.read.schema(
    'facility_id string, service string, source_type string, publisher string, url string, '
    'checked string, event string, published string, excerpt string, rationale string, review_status string, '
    'operating_status string, existence_confidence double, map_id string'
).json(path)
valid_ids = spark.table('databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities').select(
    F.col('unique_id').alias('facility_id')
).distinct()
services = ['mri','dialysis','c_section','nicu','cardiac_surgery','burn_care','trauma_care']
source_types = ['hospital_website','hospital_directory','public_facilities','blood_banks','pmjay','pmndp','obstetric_fru','nabh','OpenStreetMap','Overture','web_search','review']
chosen = signals.join(valid_ids,'facility_id','left_semi').where(
    (F.col('review_status') == 'reviewed') & F.col('source_type').isin(source_types)
    & (F.col('service').isNull() | F.col('service').isin(services))
    & F.col('url').rlike(r'^https?://') & (F.length(F.trim('publisher')) > 0)
    & (F.length(F.trim('rationale')) > 0)
).withColumn('rationale', F.concat_ws(' · ', 'rationale',
    F.when(F.col('operating_status').isNotNull(),F.concat(F.lit('Map operating status: '),'operating_status')),
    F.when(F.col('existence_confidence').between(0,1),F.concat(F.lit('Map existence confidence: '),'existence_confidence')),
    F.when(F.col('map_id').isNotNull(),F.concat(F.lit('Map ID: '),'map_id'))))
for field in ('checked','event','published'):
    chosen = chosen.withColumn(field,F.expr(f'try_cast({field} as date)'))
chosen = chosen.where(F.col('checked').isNotNull()).withColumn(
    'signal_id',F.sha2(F.concat_ws('|', 'facility_id', F.coalesce('service',F.lit('')), 'source_type','url',F.coalesce('excerpt',F.lit(''))),256)
).select('signal_id','facility_id','service','source_type','publisher','url','checked','event','published','excerpt','rationale','review_status')
from pyspark.sql import Window
priority = Window.partitionBy('signal_id').orderBy(F.col('checked').desc(),F.col('rationale'))
chosen = chosen.withColumn('version',F.row_number().over(priority)).where('version=1').drop('version')
display(chosen.limit(30))

# COMMAND ----------

if dbutils.widgets.get('mode') == 'Apply':
    chosen.createOrReplaceTempView('reviewed_signals_to_merge')
    spark.sql("""
      MERGE INTO workspace.referral_verification.frontend_source_signals AS target
      USING reviewed_signals_to_merge AS source ON target.signal_id=source.signal_id
      WHEN MATCHED AND source.checked >= target.checked THEN UPDATE SET *
      WHEN NOT MATCHED THEN INSERT *
    """).show()
