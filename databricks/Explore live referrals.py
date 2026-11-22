# Databricks notebook source
# MAGIC %md
# MAGIC # Atlas live referrals
# MAGIC Enter a location and choose a service from the Unity Catalog service catalog. Searches use the same ranking and directory functions as the app. Results include their underlying claims, evidence and any recommended call.

# COMMAND ----------

import json
from datetime import datetime, timezone

REFERRALS = 'workspace.referral_verification'
RANKING = 'workspace.saboot'

def payload(statement, **parameters):
    return json.loads(spark.sql(statement,args=parameters).first().payload)

catalog = payload(f'SELECT payload FROM {REFERRALS}.referral_service_catalog()')
service_ids = [item['id'] for item in catalog]
dbutils.widgets.text('location', '', 'Location')
dbutils.widgets.dropdown('service', service_ids[0], service_ids, 'Service')

# COMMAND ----------

location = dbutils.widgets.get('location').strip()
service = dbutils.widgets.get('service')
if not location:
    print('Enter a locality and state, a six-digit PIN, or latitude and longitude.')
else:
    query = {'location':location, 'service':service}
    general_care = service in ('emergency_care','primary_care')
    ranked = {} if general_care else payload(
        f'SELECT payload FROM {RANKING}.rank_referrals(:location,:service)', **query)
    if ranked.get('rankingAvailable'):
        result = ranked
        print('Ranked by expected time to care')
    else:
        result = payload(f'SELECT payload FROM {REFERRALS}.search_referrals(:location,:service)', **query)
        print('Directory results' if general_care else 'Directory results · this service has insufficient verified labels for model ranking.')
    context = payload(f'SELECT payload FROM {REFERRALS}.referral_context(:submitted)',
                      submitted=datetime.now(timezone.utc).replace(tzinfo=None).isoformat())
    print(result['location'], service, context['localTime'] + ' IST')
    if result.get('message'):
        print(result['message'])
    else:
        if service == 'emergency_care':
            candidates = [('emergency listing', row) for row in result.get('baseline', []) if row['tier']>=0]
        else:
            candidates = [(group,row) for group in ('supported','leads') for row in result[group]]
        if ranked.get('rankingAvailable'):
            candidates.sort(key=lambda pair: pair[1]['rank'])
        rows = []
        for rank,(group,row) in enumerate(candidates,1):
            rows.append((rank,group,row['name'],row.get('km'),row.get('p'),row.get('etcMin'),
                         row['id']==result.get('callFirst'),row.get('phone'),
                         json.dumps(row.get('evidence',[]),ensure_ascii=False)))
        for row in result.get('exclusions',[]):
            rows.append((None,'withheld',row['name'],row.get('km'),row.get('p'),None,False,None,
                         json.dumps(row.get('evidence',[]),ensure_ascii=False)))
        if rows:
            display(spark.createDataFrame(rows,'rank int, category string, facility string, distance_km double, probability double, expected_minutes double, call_first boolean, phone string, evidence_json string'))
        else:
            print('No usable facility results for this search.')
