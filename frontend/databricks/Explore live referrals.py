# Databricks notebook source
# MAGIC %md
# MAGIC # Find the right care | Submission notebook
# MAGIC Enter a locality or district and state, a six-digit PIN, or latitude and longitude in India. Choose a challenge service or care setting. This notebook runs the data-side pipeline. The app uses OpenAI to classify free text against the Unity Catalog service catalog, then calls the same Databricks search function shown below. The notebook lets you enter the equivalent service directly. Search evidence describes facility claims and historical records. Current service availability and referral acceptance require confirmation.

# COMMAND ----------

dbutils.widgets.text('location', 'Jaipur, Rajasthan', 'Location')
dbutils.widgets.dropdown('service', 'c_section', ['mri','dialysis','c_section','nicu','cardiac_surgery','burn_care','trauma_care','emergency_care','primary_care'], 'Service')
dbutils.widgets.dropdown('demo', 'Live search', ['Live search','Palwal MRI','Bhagalpur dialysis'], 'Preset')

# COMMAND ----------

import json

catalog = json.loads(spark.sql(
    'SELECT payload FROM workspace.referral_verification.referral_service_catalog()'
).first().payload)

preset = dbutils.widgets.get('demo')
if preset == 'Live search':
    matched = next(service for service in catalog if service['id'] == dbutils.widgets.get('service'))
    print('Catalog service:', matched['label'], '· Intake terms:', ', '.join(matched['keywords']))
    payload = spark.sql(
        'SELECT payload FROM workspace.referral_verification.search_referrals(:location, :service)',
        args={'location':dbutils.widgets.get('location'), 'service':matched['id']}
    ).first().payload
else:
    payload = spark.sql(
        'SELECT payload FROM workspace.referral_verification.frontend_scenarios WHERE scenario = :scenario',
        args={'scenario':'palwal' if preset == 'Palwal MRI' else 'bhagalpur'}
    ).first().payload

result = json.loads(payload)
print(result['location'], result['service'], result.get('cutoff') or result.get('originMethod') or 'Latest reviewed evidence')
if result['message']:
    print(result['message'])
else:
    rows = [(section, r['name'], r.get('km'), r.get('baselineRank'), r.get('rank'), r.get('label') or r.get('claimType'),
             (r.get('claim') or {}).get('excerpt'), r['id'], json.dumps(r['evidence'], ensure_ascii=False))
            for section in ('baseline','supported','exclusions','leads') for r in result[section]]
    if rows:
        display(spark.createDataFrame(rows, 'section string, facility string, km double, baseline_rank int, supported_rank int, claim string, virtue_excerpt string, facility_id string, evidence_json string'))
    else:
        print('No nearby keyword hits or reviewed evidence for this service.')
