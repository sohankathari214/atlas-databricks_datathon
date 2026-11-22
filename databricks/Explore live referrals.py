# Databricks notebook source
# MAGIC %md
# MAGIC # Find the right care | Submission notebook
# MAGIC Search the live directory, compare dated replays, and inspect scraped source leads in one notebook. A directory lead is not current availability. Road closures and hospital capacity are unknown unless a verified feed supplies them.
# MAGIC
# MAGIC The app classifies free text against the Unity Catalog service catalog. This notebook uses the equivalent service directly. Scraped records remain in the research table until campus, dates, and service scope are reviewed.

# COMMAND ----------

dbutils.widgets.text('location', 'Parel, Mumbai', 'Location')
dbutils.widgets.dropdown('service', 'cardiac_surgery', ['mri','dialysis','c_section','nicu','cardiac_surgery','burn_care','trauma_care','emergency_care','primary_care'], 'Service')
dbutils.widgets.dropdown('demo', 'Parel coronary bypass', ['Live search','Parel coronary bypass','Patna dialysis','Palwal MRI','Bhagalpur dialysis','Monsoon evening example','Scraped source leads'], 'Preset')

# COMMAND ----------

import json
from datetime import datetime, timezone

schema = 'workspace.referral_verification'
preset = dbutils.widgets.get('demo')
query = lambda sql, **args: spark.sql(sql, args=args)
def payload(sql, **args):
    return json.loads(query(sql, **args).first().payload)

def explain(row, group, service):
    if group == 'supported':
        return 'Reviewed evidence supports prior service at this campus.'
    narrow = row.get('claimSubtype') in ('sncu_level2', 'stabilization_documented') or (
        service == 'c_section' and row.get('claimSubtype') != 'emergency_obstetric_capability')
    if row.get('claimType') == 'explicit_onsite' and not narrow:
        return 'On-site claim ranked before broader mentions. Distance breaks ties.'
    return 'Highest-ranked eligible directory lead by documented scope and distance.'

if preset == 'Scraped source leads':
    display(spark.table(f'{schema}.demo_scraped_source_leads').orderBy('checked', ascending=False))
else:
    clock = datetime.now(timezone.utc)
    examples = {
        'Parel coronary bypass': ('Parel, Mumbai', 'cardiac_surgery'),
        'Patna dialysis': ('800014', 'dialysis'),
        'Monsoon evening example': ('Parel, Mumbai', 'cardiac_surgery'),
    }
    replay = {'Palwal MRI': 'palwal', 'Bhagalpur dialysis': 'bhagalpur'}.get(preset)
    if replay:
        result = payload(f'SELECT payload FROM {schema}.frontend_scenarios WHERE scenario = :scenario', scenario=replay)
        print('Historical replay cutoff:', result.get('cutoff') or 'latest reviewed evidence')
    else:
        location, service = examples.get(preset, (dbutils.widgets.get('location'), dbutils.widgets.get('service')))
        result = payload(f'SELECT payload FROM {schema}.search_referrals(:location, :service)', location=location, service=service)
        if preset == 'Monsoon evening example':
            clock = datetime(2026, 7, 23, 15, 30, tzinfo=timezone.utc)
            print('Illustrative submission timestamp. Facility results still use the live directory.')
        context = payload(f'SELECT payload FROM {schema}.referral_context(:submitted)', submitted=clock.replace(tzinfo=None).isoformat())
        print(f'Submitted {context["localTime"]} IST · Overnight: {context["overnight"]} · Southwest monsoon window: {context["southwestMonsoonWindow"]}')
        print('Road closures and capacity unknown. Verify receiving hours and check local advisories: https://mausam.imd.gov.in/')
    print(result['location'], result['service'])
    if result.get('message'):
        print(result['message'])
    else:
        choices = [(key, row) for key in ('supported', 'leads') for row in result.get(key, [])]
        if result['service'] == 'emergency_care' and not replay:
            choices = [('emergency listing', row) for row in result.get('baseline', []) if row['tier'] >= 0]
        rows = []
        for rank, (group, row) in enumerate(choices, 1):
            reason = ('Closest returned emergency department listing.' if group == 'emergency listing'
                      else explain(row, group, result['service'])) if rank == 1 else None
            rows.append((rank, group, row['name'], row.get('km'), reason, json.dumps(row['evidence'], ensure_ascii=False)))
        for group in ('exclusions', 'baseline'):
            rows += [(None, group, row['name'], row.get('km'), None, json.dumps(row['evidence'], ensure_ascii=False))
                     for row in result.get(group, [])]
        if rows:
            display(spark.createDataFrame(rows, 'rank int, group string, facility string, distance_km double, why_first string, evidence_json string'))
        else:
            print('No nearby directory hits or reviewed evidence for this service.')
