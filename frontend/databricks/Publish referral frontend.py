# Databricks notebook source
from datetime import date
from html import escape
from urllib.parse import quote_plus
from pyspark.sql import functions as F, Window

schema = 'workspace.referral_verification'
facilities = spark.table('databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities')
origins = spark.table(schema + '.city_origins')
claims = spark.table(schema + '.service_claims')
civil = 'a948a2d7-b57a-4df6-b082-d8e5b86a214b'
jindal = '050479fe-82a8-404b-a41b-a61d15eb9577'
mayaganj = '29903d8a-3433-4240-b1eb-91094a7551d4'
sadar = 'b94c3b56-febe-41cc-9219-3ba755fe2d4c'
hindustan = 'https://www.livehindustan.com/bihar/bhagalpur/story-dialysis-unit-started-in-mayaganj-hospital-9337620.html'
jindal_page = 'https://jindalhospitalcancercentre.com/radiology/'

evidence = [
 (civil,'','identity',None,None,'District Palwal','https://palwal.gov.in/public-utility/civil-hospital/','New Sohna Road, Near Agra Chowk, Palwal','','','Agra Chowk and Panchwati Colony identify the main Civil Hospital in Palwal. The listing provides an address, not an exact surveyed pin.'),
 (civil,'mri','planned','2026-10-28','2026-10-28','Amar Ujala','https://www.amarujala.com/haryana/palwal/mri-facility-to-be-introduced-at-the-district-hospital-palwal-news-c-24-1-pal1008-129649-2026-10-28','जिला नागरिक अस्पताल में अभी एमआरआई मशीन उपलब्ध नहीं है।','The district Civil Hospital does not yet have an MRI machine.','MRI approved, machine absent','Report names the main district Civil Hospital. The approval is for a future public-private service.'),
 (jindal,'','identity',None,None,'Jindal Hospital',jindal_page,'DM Road,Near Omaxe City, Palwal, Haryana 121102','','','Street, landmark, and phone +91-9755591860 match the Virtue row. The hospital site may also be the original Virtue source.'),
 (jindal,'mri','listed',None,None,'Jindal Hospital',jindal_page,'MRI Scan','','MRI listed by the hospital','Same page identifies this campus by street, landmark, and phone. Undated self-report; no procedure counts or slot confirmation.'),
 (mayaganj,'','identity',None,None,'JLNMCH','https://jlnmchbgp.org/contact.php','Jawahar Lal Nehru Medical College & Hospital Mayaganj, Bhagalpur, Bihar 812001','','','The full hospital name, Mayaganj locality and phone 0641-2300217 match Virtue. Undated identity cross-check reviewed after the historical replay.'),
 (mayaganj,'dialysis','interrupted','2024-02-05','2024-02-17','Hindustan',hindustan,'पांच फरवरी को डायलिसिस यूनिट बंद हो गई थी।','The dialysis unit had closed on February 5.','Dialysis interruption','Same report as reopening. Names JLNMCH and Mayaganj, and attributes interruption to water quality.'),
 (mayaganj,'dialysis','delivered','2024-02-17','2024-02-17','Hindustan',hindustan,'शनिवार को चार मरीजों का डायलिसिस किया गया।','Four patients underwent dialysis on Saturday.','Dialysis documented','The report names JLNMCH and Mayaganj and quotes the unit lead. Completed care on that date.'),
 (mayaganj,'dialysis','interrupted','2026-05-27','2026-05-28','Hindustan','https://www.livehindustan.com/bihar/bhagalpur/story-dialysis-services-halted-at-mayaganj-hospital-due-to-filter-burst-201779909114347.html','बुधवार से मायागंज अस्पताल में डायलिसिस सेवा बंद हो गये।','Dialysis service at Mayaganj Hospital stopped on Wednesday.','Dialysis interruption reported','Water filter failed. Scope is the main Mayaganj unit. Restoration and current status are unknown.'),
 (sadar,'','location_conflict',None,None,'East Singhbhum district','https://jamshedpur.nic.in/health/','Khasmahal, Parsudih, Jamshedpur','','','The official Sadar Hospital address does not match the Virtue address. The listed name alone is insufficient to resolve which campus this row describes.'),
 (sadar,'','location_conflict',None,None,'East Singhbhum district','https://jamshedpur.nic.in/landbank/','22 Deg 12 Min – 23 Deg 01 Min North','','','Virtue pin 25.779234, 87.477402 lies outside the listed district extent. It computes to 77.2 km from the seeded Bhagalpur origin; the demo withholds it.')
]
reviewed = spark.createDataFrame(evidence, 'id string, service string, kind string, event string, published string, publisher string, url string, excerpt string, translation string, label string, rationale string').withColumn('checked',F.lit('2026-11-21'))
reviewed.createOrReplaceTempView('demo_reviewed_evidence')

# COMMAND ----------

def search(location, service, cutoff=None):
 city, sep, state = location.partition(',')
 if not sep or not city.strip() or not state.strip():
  return [], 'Enter a city and state, for example Palwal, Haryana.'
 city, state = city.strip().lower(), state.strip().lower()
 origin = origins.where((F.lower('origin_city') == city) & (F.lower('state') == state)).take(2)
 if len(origin) != 1 or origin[0].origin_latitude is None or origin[0].origin_longitude is None:
  return [], 'This city and state do not have a usable origin in the demo lookup.'
 lat, lon = float(origin[0].origin_latitude), float(origin[0].origin_longitude)
 if not (7 < lat < 38 and 68 < lon < 98):
  return [], 'The stored origin coordinates are unusable.'
 alias = {'mri':r'mri|magnetic resonance imaging','dialysis':r'(?:hemo|haemo)?dialysis'}[service]
 token = r'(?i)\b(?:'+alias+r')\b'
 checked = spark.table('demo_reviewed_evidence')
 history = checked.where(F.col('service') == service)
 if cutoff:
  history = history.where((F.col('published') <= cutoff) & (F.col('event') <= cutoff))
 recent = Window.partitionBy('id').orderBy(F.col('event').desc_nulls_last(), F.col('published').desc_nulls_last(), 'kind')
 latest = history.withColumn('recency', F.row_number().over(recent)).where('recency = 1').select('id','kind','event','label')
 records = checked.where(F.col('kind').isin('identity','location_conflict')).unionByName(history).groupBy('id').agg(
  F.max(F.when(F.col('kind') == 'identity',F.col('excerpt'))).alias('campus_address'),
  F.sort_array(F.collect_list(F.struct('event','published','publisher','url','excerpt','translation','rationale','kind','checked')),asc=False).alias('evidence'))
 terms = r'(?i)[^"\n.!?]{0,110}\b(?:'+alias+r')\b[^"\n.!?]{0,130}'
 field_names = ['description','procedure','capability','equipment','specialties']
 excerpts = F.filter(F.array(*[F.struct(F.lit(c).alias('field'),F.trim(F.regexp_extract(F.col(c),terms,0)).alias('quote')) for c in field_names]),lambda x: F.length(x['quote']) > 0)
 source_urls = F.from_json('source_urls','array<string>')
 base = facilities.select(F.col('unique_id').alias('id'),F.col('name'),F.col('address_city').alias('city'),F.col('address_stateOrRegion').alias('state'),
  F.concat_ws(', ', 'address_line1','address_line2','address_city','address_stateOrRegion','address_zipOrPostcode').alias('address'),
  F.expr('try_cast(latitude as double)').alias('lat'), F.expr('try_cast(longitude as double)').alias('lon'),excerpts.alias('hits'),source_urls.alias('source_urls'),
  F.concat_ws(' ', *field_names).rlike(token).alias('keyword'))
 claim_priority = F.when(F.col('claim_type').isin('explicit_absence','explicit_negative','negated','provided_elsewhere','planned'),0).when(F.col('claim_type')=='explicit_onsite',1).otherwise(2)
 claim_order = Window.partitionBy('facility_id').orderBy(claim_priority,F.col('is_primary_evidence').desc_nulls_last(),'source_field','verbatim_excerpt')
 context = claims.where(F.col('service') == service).withColumn('rn',F.row_number().over(claim_order)).where('rn=1').select(F.col('facility_id').alias('id'), 'claim_type','source_field','verbatim_excerpt')
 pin = F.col('lat').between(7,38) & F.col('lon').between(68,98)
 a = F.pow(F.sin(F.radians(F.col('lat')-lat)/2),2) + F.cos(F.radians(F.lit(lat)))*F.cos(F.radians('lat'))*F.pow(F.sin(F.radians(F.col('lon')-lon)/2),2)
 raw_km = F.when(pin,6371*2*F.asin(F.sqrt(F.least(F.lit(1.0),a))))
 flags = checked.where(F.col('kind') == 'location_conflict').select('id').distinct().withColumn('conflict',F.lit(True))
 nearby = base.join(flags,'id','left').fillna({'conflict':False}).withColumn('raw_km',raw_km).withColumn('km',F.when(~F.col('conflict'),F.col('raw_km'))).where(
  (F.col('raw_km') <= 100) | ((F.lower(F.trim('city')) == city) & (F.lower(F.trim('state')) == state)))
 baseline_order = Window.orderBy(F.col('km').asc_nulls_last(),'name','id')
 baseline = nearby.where('keyword AND km IS NOT NULL').withColumn('baseline_rank',F.row_number().over(baseline_order)).select('id','baseline_rank')
 result = nearby.join(latest,'id','left').join(records,'id','left').join(baseline,'id','left').join(context,'id','left').where(
  F.col('keyword') | F.col('kind').isNotNull()).withColumn('hit',F.get('hits',0))
 negative = F.expr("exists(hits, h -> regexp_like(h.quote, '(?i)(no |without |lacks |not available|not offered|unavailable|referred elsewhere|referred to|planned|proposed|will be introduced)'))")
 result = result.withColumn('tier',F.when(F.col('conflict'),-3).when(F.col('kind').isin('planned','interrupted'),-2)
  .when(F.col('campus_address').isNotNull() & (F.col('kind') == 'delivered'),3)
  .when(F.col('campus_address').isNotNull() & (F.col('kind') == 'listed'),2)
  .when(negative | F.col('claim_type').isin('explicit_absence','explicit_negative','negated','provided_elsewhere','planned'),-1).otherwise(0))
 ordering = Window.orderBy(F.col('tier').desc(), F.col('km').asc_nulls_last(),'name','id')
 ranked = result.where('tier > 0').withColumn('evidence_rank',F.row_number().over(ordering)).select('id','evidence_rank')
 result = result.join(ranked,'id','left')
 page_order = Window.partitionBy('tier').orderBy(F.col('km').asc_nulls_last(),'name','id')
 return result.withColumn('slot',F.row_number().over(page_order)).where('baseline_rank <= 5 OR evidence_rank <= 5 OR (slot <= 2 AND tier <= 0)').collect(), ''



# COMMAND ----------

import json

scenario_inputs = [
    ('palwal', 'Palwal, Haryana', 'mri', None),
    ('bhagalpur', 'Bhagalpur, Bihar', 'dialysis', '2024-02-18'),
    ('palwal-dialysis', 'Palwal, Haryana', 'dialysis', None),
    ('bhagalpur-mri', 'Bhagalpur, Bihar', 'mri', None),
]

def public_result(row):
    hit = row.hit
    return {
        'id': row.id,
        'name': 'Mayaganj Hospital (JLNMCH)' if row.id == mayaganj else row.name,
        'place': ', '.join(value for value in [row.city, row.state] if value),
        'address': row.campus_address or row.address,
        'virtueAddress': row.address,
        'km': round(row.km, 1) if row.km is not None else None,
        'campusCorroborated': bool(row.campus_address),
        'kind': row.kind,
        'event': row.event,
        'label': row.label,
        'tier': row.tier,
        'baselineRank': row.baseline_rank,
        'rank': row.evidence_rank,
        'claim': {'field': hit.field, 'excerpt': hit.quote} if hit else None,
        'sourceUrls': [url for url in (row.source_urls or []) if url][:4],
        'evidence': [e.asDict() for e in (row.evidence or [])],
    }

published = []
for key, location, service, cutoff in scenario_inputs:
    rows, message = search(location, service, cutoff)
    baseline = sorted((r for r in rows if r.baseline_rank), key=lambda r: r.baseline_rank)[:3]
    supported = sorted((r for r in rows if r.evidence_rank), key=lambda r: r.evidence_rank)[:3]
    exclusions = sorted((r for r in rows if r.tier < 0), key=lambda r: (r.tier != -2, r.tier, r.baseline_rank or 999))[:2]
    leads = sorted((r for r in rows if r.tier == 0), key=lambda r: r.baseline_rank or 999)[:2]
    payload = dict(location=location, service=service, cutoff=cutoff, message=message,
                   baseline=list(map(public_result, baseline)), supported=list(map(public_result, supported)),
                   exclusions=list(map(public_result, exclusions)), leads=list(map(public_result, leads)))
    published.append((key, json.dumps(payload, ensure_ascii=False)))

# Publish all scenarios together so the app always sees a complete set.
target = schema + '.frontend_scenarios'
spark.createDataFrame(published, 'scenario string, payload string').withColumn(
    'refreshed_at', F.current_timestamp()
).write.mode('overwrite').saveAsTable(target)
print(f'Published {len(published)} scenarios to {target}')
