# Databricks notebook source
# MAGIC %md
# MAGIC # Atlas · Evidence, expected time, and evaluation
# MAGIC Run this notebook on Databricks Free Edition serverless Python. It reads Unity Catalog and CSVs in the gold_inputs volume. Collection runs in the separate Source research pipeline. This notebook makes no external API requests.
# MAGIC
# MAGIC The target is documented service capability, a proxy for being able to obtain care. Modelled travel and penalties are scenario estimates. The gold sample is positive-unlabelled and biased toward public hospitals. The evaluation measures performance on labelled candidates from held-out districts, not patient outcomes.

# COMMAND ----------

import hashlib
import itertools
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
import pandas as pd
from scipy.special import expit, logit
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedGroupKFold, GridSearchCV

OUT = 'workspace.saboot'
DATA = 'databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset'
REF = 'workspace.referral_verification'
GOLD = Path('/Volumes/workspace/saboot/gold_inputs')
SEED = 2026
MIN_CLASS = 30
MIN_SEARCHES = 30
SERVICES = ('mri','dialysis','c_section','nicu','cardiac_surgery','burn_care','trauma_care')
ASSUMPTIONS = {
    'kappa': (1.3, [1.2, 1.4, 1.6], 'Road distance / straight-line distance'),
    'v': (30, [20, 40], 'Average road speed, km/h'),
    't0': (10, [0, 20], 'Transport setup, minutes'),
    'h': (30, [15, 60], 'Time lost when turned away, minutes'),
    'H': (240, [120, 480], 'Penalty if care is still unavailable, minutes'),
    'c_call': (3, [1, 10], 'Call cost and recommendation threshold, minutes'),
    'm': (10, [5, 20], 'Service-wide prior shrinkage strength'),
}
DEFAULT = {k: x[0] for k, x in ASSUMPTIONS.items()}
spark.sql(f'CREATE SCHEMA IF NOT EXISTS {OUT}')
spark.sql(f'CREATE VOLUME IF NOT EXISTS {OUT}.gold_inputs')

def describe(table, optional=False):
    if not spark.catalog.tableExists(table):
        if optional:
            print(f'{table}: unavailable')
            return set()
        raise RuntimeError(f'Missing required Unity Catalog object {table}')
    columns = [(r.col_name, r.data_type) for r in spark.sql(f'DESCRIBE {table}').collect()
               if r.col_name and not r.col_name.startswith('#') and r.data_type]
    print(f'{table}: ' + ', '.join(f'{name} {kind}' for name, kind in columns))
    return {name for name, _ in columns}

tables = {n: f'{DATA}.{n}' for n in ('facilities','india_post_pincode_directory')}
tables.update({n: f'{REF}.{n}' for n in ('v_service_best_claims','facility_location_flags',
               'frontend_source_signals','external_evidence_ext','city_origins','frontend_scenarios')})
for name in ('silver_facilities','silver_claims','silver_phones','silver_sources','silver_post_offices','silver_pin_centroids'):
    tables[name] = f'{OUT}.{name}'
schemas = {n: describe(t, n.startswith('silver_')) for n,t in tables.items()}

def read(name, columns=None):
    frame = spark.table(tables[name])
    return (frame.select(*columns) if columns else frame).toPandas()

def write(name, rows, schema):
    frame = spark.createDataFrame(list(rows), schema)
    frame.write.mode('overwrite').option('overwriteSchema','true').saveAsTable(f'{OUT}.{name}')
    print(f'{name}: {frame.count()} rows')
    return frame

display(spark.createDataFrame([(k,float(v),', '.join(map(str,g)),why) for k,(v,g,why) in ASSUMPTIONS.items()],
                             'parameter string, default_value double, sensitivity string, rationale string'))

# COMMAND ----------

# MAGIC %md
# MAGIC ## A. Facility identity and gold labels
# MAGIC Upload `gold_manual.csv`, `pmndp*.csv`, or `nhm_fru*.csv` into `/Volumes/workspace/saboot/gold_inputs`.
# MAGIC The manual file uses facility_id, service, y, method, source_url, labeller, date. Registry files use name, district, state, pin, phone, source_url, date. Use one row per campus. For an FRU, include only a functional emergency obstetric unit with documented C-section capability. An optional `pmndp_complete_states.csv` contains state, source_url, date and a true complete flag only for audited complete snapshots.
# MAGIC
# MAGIC Registry matching requires shared PIN or district and state. Score = name-token Jaccard + 0.3 PIN + 0.3 phone. A unique top match at 0.6 or above is accepted. Scores from 0.4 to below 0.6 and ties at the top go to review. A facility can be ruled negative only by a manual label or the explicit complete-state rule. Disagreeing labels are reviewed.

# COMMAND ----------

def norm(value):
    value = unicodedata.normalize('NFKC', str(value or '')).casefold()
    return ' '.join(re.findall(r'[^\W_]+', value, flags=re.UNICODE))

def pin(value):
    match = re.search(r'\b[1-9]\d{5}\b', str(value or ''))
    return match.group() if match else ''

def phones(value):
    return {re.sub(r'\D','', token)[-10:] for token in re.findall(r'\+?\d[\d ()-]{7,17}\d', str(value or ''))
            if len(re.sub(r'\D','',token)) >= 10}

def tokens(value):
    return set(norm(value).split()) - {'hospital','district','govt','government','civil','centre','center','the','of'}

def date_value(value):
    return pd.to_datetime(value, errors='coerce', utc=True)

def url_key(value):
    u = urlsplit(str(value or ''))
    return (u.hostname or '').removeprefix('www.') + u.path.rstrip('/').lower() if u.scheme in ('http','https') and u.hostname else ''

def csvs(pattern, required):
    rows = []
    for path in sorted(GOLD.glob(pattern)):
        if pattern == 'pmndp*.csv' and path.name == 'pmndp_complete_states.csv':
            continue
        frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding='utf-8-sig')
        missing = set(required) - set(frame.columns)
        if missing:
            raise ValueError(f'{path.name} is missing {sorted(missing)}')
        print(f'{path.name}: {len(frame)} rows')
        rows.extend(frame.to_dict('records'))
    return rows

facility_columns = ['unique_id','name','facilityTypeId','operatorTypeId','address_city','address_stateOrRegion',
    'address_zipOrPostcode','latitude','longitude','officialPhone','phone_numbers',
    'description','procedure','capability','equipment','specialties','officialWebsite','facebookLink',
    'address_line1','address_line2','source_urls']
fac = read('facilities', facility_columns).fillna('').sort_values('unique_id').drop_duplicates('unique_id')
fac = fac.rename(columns={'unique_id':'facility_id','address_stateOrRegion':'state','address_city':'city'})
fac['pin'] = fac.address_zipOrPostcode.map(pin)
fac['state'] = fac.state.map(norm)
fac['public'] = fac.operatorTypeId.map(norm).str.contains(r'\b(?:government|public|govt|municipal|state|central)\b', regex=True)
operator = fac.operatorTypeId.map(norm)
operator = operator.where(operator.eq('private'), 'unknown').mask(fac.public, 'public')
fac['group'] = operator.str.cat(fac.facilityTypeId.map(norm).replace('', 'unknown'), sep=':')
fac['name_tokens'] = fac.name.map(tokens)
fac['phones'] = (fac.officialPhone + ' / ' + fac.phone_numbers).map(phones)
fac['text'] = fac[['description','procedure','capability','equipment','specialties']].agg(' '.join, axis=1)
for field in ('latitude','longitude'):
    fac[field] = pd.to_numeric(fac[field], errors='coerce')

postal = read('india_post_pincode_directory',['pincode','district','statename','latitude','longitude']).fillna('')
postal['pin'] = postal.pincode.map(pin)
postal['state'], postal['district'] = postal.statename.map(norm), postal.district.map(norm)
for field in ('latitude','longitude'):
    postal[field] = pd.to_numeric(postal[field],errors='coerce')
usable_postal = postal.loc[postal.latitude.between(6,38) & postal.longitude.between(68,98)]
centres = usable_postal.groupby(['state','district'])[['latitude','longitude']].median()
pin_districts = (postal.loc[postal.pin.ne('') & postal.district.ne('')]
                 .groupby(['pin','state']).district.agg(lambda vals: next(iter(set(vals))) if len(set(vals)) == 1 else ''))
fac['district'] = [pin_districts.get((p,s),'') or (norm(c) if (s,norm(c)) in centres.index else '')
                   for p,s,c in zip(fac.pin,fac.state,fac.city)]

flags = read('facility_location_flags')
withheld = set(flags.loc[flags.distance_ranking_withheld.fillna(False),'unique_id'])
fac['location_conflict'] = fac.facility_id.isin(withheld)
if schemas['silver_facilities']:
    cols = schemas['silver_facilities']
    id_col = next((c for c in ('facility_id','unique_id') if c in cols),None)
    lat_col = next((c for c in ('clean_latitude','resolved_latitude','latitude') if c in cols),None)
    lon_col = next((c for c in ('clean_longitude','resolved_longitude','longitude') if c in cols),None)
    if id_col and lat_col and lon_col:
        silver = read('silver_facilities').sort_values(id_col).drop_duplicates(id_col).set_index(id_col)
        lat = pd.to_numeric(fac.facility_id.map(silver[lat_col]), errors='coerce')
        lon = pd.to_numeric(fac.facility_id.map(silver[lon_col]), errors='coerce')
        use = lat.between(6,38) & lon.between(68,98)
        fac.loc[use,'latitude'], fac.loc[use,'longitude'] = lat[use],lon[use]
        if 'distance_ranking_withheld' in cols:
            fac['location_conflict'] |= fac.facility_id.map(silver.distance_ranking_withheld).eq(True)
        elif 'location_confidence' in cols:
            fac['location_conflict'] |= fac.facility_id.map(silver.location_confidence).astype(str).str.lower().isin(['conflict','conflicting'])
        print(f'Silver coordinates used for {int(use.sum())} facilities')
if schemas['silver_phones']:
    cols = schemas['silver_phones']
    id_col = next((c for c in ('facility_id','unique_id') if c in cols),None)
    phone_col = next((c for c in ('phone_e164','normalized_phone','phone') if c in cols),None)
    if id_col and phone_col:
        silver_phone = read('silver_phones',[id_col,phone_col]).fillna('').groupby(id_col)[phone_col].agg(' / '.join).map(phones)
        fac['phones'] = [p | silver_phone.get(i,set()) for i,p in zip(fac.facility_id,fac.phones)]

by_id = fac.set_index('facility_id')
by_pin = {key: list(part.index) for key,part in by_id.groupby('pin') if key}
by_district = {key: list(part.index) for key,part in by_id.groupby(['state','district']) if all(key)}
raw_labels, queue, bands = [], [], {'accepted':0,'review':0,'rejected':0}
required = ['facility_id','service','y','method','source_url','labeller','date']
for row in csvs('gold_manual.csv',required):
    if (row['facility_id'] not in by_id.index or row['service'] not in SERVICES or row['y'] not in ('0','1')
        or row['method'].lower() not in ('call','website','registry') or not row['labeller'].strip()
        or (row['method'].lower() != 'call' and not url_key(row['source_url'])) or pd.isna(date_value(row['date']))):
        raise ValueError('Invalid gold_manual row. Check facility ID, service, y, method, provenance and date.')
    raw_labels.append((row['facility_id'],row['service'],int(row['y']),'manual_' + row['method'].lower(),row['source_url'],row['date']))

matched_dialysis, possible_dialysis, represented_states = set(),set(),set()
for pattern,service,rule in [('pmndp*.csv','dialysis','pmndp_registry'),('nhm_fru*.csv','c_section','nhm_functional_fru')]:
    for row in csvs(pattern,['name','district','state','pin','phone','source_url','date']):
        if not url_key(row['source_url']) or pd.isna(date_value(row['date'])) or not norm(row['name']):
            raise ValueError(f'Invalid {rule} registry provenance or name.')
        state,district,postal_pin = norm(row['state']),norm(row['district']),pin(row['pin'])
        identifiers = set(by_pin.get(postal_pin,[])) | set(by_district.get((state,district),[]))
        name_tokens, dial_numbers = tokens(row['name']), phones(row['phone'])
        scored = []
        for identifier in sorted(identifiers):
            f = by_id.loc[identifier]
            combined = name_tokens | f.name_tokens
            name_score = len(name_tokens & f.name_tokens) / len(combined) if combined else 0
            score = name_score + .3 * bool(postal_pin and postal_pin == f.pin) + .3 * bool(dial_numbers & f.phones)
            scored.append((round(score,10),identifier))
        scored.sort(key=lambda pair: (-pair[0],pair[1]))
        if service == 'dialysis':
            possible_dialysis.update(i for score,i in scored if score >= .4)
            if state:
                represented_states.add(state)
        if scored and scored[0][0] >= .6 and (len(scored)==1 or scored[0][0] > scored[1][0]):
            _,identifier = scored[0]
            bands['accepted'] += 1
            raw_labels.append((identifier,service,1,rule,row['source_url'],row['date']))
            if service == 'dialysis':
                matched_dialysis.add(identifier)
        elif scored and scored[0][0] >= .4:
            bands['review'] += 1
            queue.extend((rule,row['name'],service,row['source_url'],i,float(score),'ambiguous registry campus')
                         for score,i in scored if score >= .4)
        else:
            bands['rejected'] += 1

claims = read('v_service_best_claims').fillna('')
claims = claims.loc[claims.service.isin(SERVICES)].sort_values(['facility_id','service']).drop_duplicates(['facility_id','service'])
dialysis_claim = set(claims.loc[claims.service.eq('dialysis') & claims.best_claim_type.eq('explicit_onsite'),'facility_id'])
for row in csvs('pmndp_complete_states.csv',['state','source_url','date','complete']):
    state = norm(row['state'])
    if row['complete'].lower() not in ('true','yes','1'):
        continue
    if state not in represented_states or not url_key(row['source_url']) or pd.isna(date_value(row['date'])):
        raise ValueError('Complete-state negatives require the corresponding dated registry rows and source.')
    for f in fac.loc[fac.public & fac.state.eq(state) & fac.facility_id.isin(dialysis_claim)].itertuples():
        if f.facility_id not in matched_dialysis | possible_dialysis:
            raw_labels.append((f.facility_id,'dialysis',0,'pmndp_complete_state_absence',row['source_url'],row['date']))

labels = pd.DataFrame(raw_labels,columns=['facility_id','service','y','label_rule','source','date'])
label_urls = {(s,url_key(u)) for _,s,_,_,u,_ in raw_labels if url_key(u)}
gold_rows = []
for (identifier,service),group in labels.groupby(['facility_id','service'],sort=True):
    if group.y.nunique() != 1:
        queue.append(('label_conflict',str(by_id.at[identifier,'name']),service,'',identifier,None,'positive and negative labels disagree'))
        continue
    chosen = sorted(group.to_dict('records'),key=lambda r: (not r['label_rule'].startswith('manual_'),-date_value(r['date']).timestamp(),r['source']))[0]
    gold_rows.append((*[chosen[k] for k in ('facility_id','service','y','label_rule','source')],
                      str(by_id.at[identifier,'district']),str(by_id.at[identifier,'state']),str(chosen['date'])))
gold_fields = ['facility_id','service','y','label_rule','source','district','state','date']
gold = pd.DataFrame(gold_rows,columns=gold_fields)
write('gold_labels',gold_rows,'facility_id string, service string, y int, label_rule string, source string, district string, state string, date string')
write('gold_review_queue',sorted(set(queue),key=str),'registry string, registry_name string, service string, source string, facility_id string, score double, reason string')
print('Registry match bands:',bands)
counts = gold.groupby(['service','y']).size().unstack(fill_value=0).reindex(index=SERVICES,columns=[0,1],fill_value=0)
print('Gold class balance (0 = negative, 1 = positive):\n',counts)
print('Facilities with an India Post district:', int(fac.district.ne('').sum()), '/', len(fac))

# COMMAND ----------

# MAGIC %md
# MAGIC ## B. Bayesian evidence and calibration
# MAGIC Fit the prior and likelihood ratios inside each training fold. Keep the strongest present feature in each family, then add log likelihood ratios across families. This assumes conditional independence between families. Families limit the influence of correlated sources.
# MAGIC Registry sources used for the gold labels, and URLs cited in gold labels, are excluded from model inputs. Features describe the evidence snapshot, so this is a geographic holdout rather than a prospective evaluation. Dates are checked independently in the historical replay.

# COMMAND ----------

FAMILIES = {
    'virtue_claim': ['claim_onsite','claim_mention','claim_absent','claim_elsewhere','claim_planned','claim_conflict'],
    'virtue_detail': ['has_equipment_count','has_staff_specialist'],
    'registry': ['on_pmjay_package','on_nabh'],
    'own_site': ['website_lists_service'],
    'dated_report': ['report_delivered','report_planned','report_interrupted'],
    'location': ['location_conflict'],
}
FEATURES = [k for family in FAMILIES.values() for k in family]
REASONS = dict(zip(FEATURES,[
    'Virtue explicitly lists on-site care','Virtue mentions related care','Virtue reports service absent',
    'Virtue directs patients elsewhere','Virtue describes planned care','Virtue has conflicting claims',
    'Virtue mentions a count of related equipment','Virtue names a related specialist',
    'Reviewed PM-JAY package listing','Reviewed NABH accreditation','Reviewed hospital website lists the service',
    'Latest dated report documents care','Latest dated report describes a plan','Latest dated report describes interruption or unavailability',
    'Campus location conflict',
]))
CLAIM_FEATURES = {'explicit_onsite':'claim_onsite','care_setting_mention':'claim_mention',
    'explicit_absence':'claim_absent','offsite_referral':'claim_elsewhere','planned':'claim_planned'}
DETAILS = {
    'mri': (r'mri (?:machines?|scanners?)',r'radiologist'),
    'dialysis': (r'(?:ha?emo)?dialysis (?:machines?|stations?)',r'nephrologist'),
    'c_section': (r'obstetric (?:operating )?theat(?:res?|ers?)',r'obstetrician'),
    'nicu': (r'nicu beds?|neonatal incubators?',r'neonatologist'),
    'cardiac_surgery': (r'cardiac (?:operating )?theat(?:res?|ers?)',r'cardiothoracic surgeon|cardiac surgeon'),
    'burn_care': (r'burn(?:s)? (?:unit )?beds?',r'burn surgeon'),
    'trauma_care': (r'trauma (?:unit )?beds?',r'trauma surgeon'),
}
pair_features, dated, dated_history = {}, {}, {}

def add(identifier,service,key):
    if identifier in by_id.index and service in SERVICES:
        pair_features.setdefault((identifier,service),set()).add(key)

def dated_feature(identifier,service,when,feature,url):
    if identifier not in by_id.index or service not in SERVICES or pd.isna(date_value(when)):
        return
    candidate = (date_value(when), feature, url)
    dated_history.setdefault((identifier,service),[]).append(candidate)
    if candidate > dated.get((identifier,service),(pd.Timestamp.min.tz_localize('UTC'),'','')):
        dated[(identifier,service)] = candidate

for r in claims.itertuples():
    add(r.facility_id,r.service,CLAIM_FEATURES.get(r.best_claim_type,'claim_mention'))
    if r.has_conflicting_evidence is True or r.has_conflicting_evidence == 1:
        add(r.facility_id,r.service,'claim_conflict')
if {'facility_id','service'}.issubset(schemas['silver_claims']):
    silver = read('silver_claims').fillna('')
    tag_col = next((c for c in ('claim_tags','tags','claim_type') if c in silver),None)
    if tag_col:
        for r in silver[['facility_id','service',tag_col]].itertuples(index=False,name=None):
            tags = set(re.findall(r'[a-z_]+',str(r[2]).lower()))
            for tag in sorted(tags):
                feature = CLAIM_FEATURES.get(tag,tag)
                if feature in FAMILIES['virtue_claim']:
                    add(r[0],r[1],feature)

for service,(equipment,staff) in DETAILS.items():
    patterns = {'has_equipment_count':r'\b(?:[1-9]\d*\s+(?:working\s+)?(?:'+equipment+r')|(?:'+equipment+r')\s*[:=]\s*[1-9]\d*)\b',
                'has_staff_specialist':r'\b(?:'+staff+r')s?\b'}
    for feature,pattern in patterns.items():
        compiled = re.compile(pattern,re.I)
        def sample(text):
            match = compiled.search(text)
            return text[max(0,match.start()-30):match.end()+35] if match else None
        excerpts = fac.text.map(sample)
        for identifier in fac.loc[excerpts.notna(),'facility_id']:
            add(identifier,service,feature)
        print(service,feature,'examples:', excerpts.dropna().head(10).tolist())

reviewed = read('frontend_source_signals').fillna('')
for r in reviewed.sort_values('signal_id').itertuples():
    if r.review_status != 'reviewed' or (r.service,url_key(r.url)) in label_urls:
        continue
    if r.source_type == 'pmjay' and r.service in SERVICES:
        add(r.facility_id,r.service,'on_pmjay_package')
    if r.source_type == 'hospital_website' and r.service in SERVICES and re.search(
       r'\b(list[s]?|provides?|offers?|available|performs?)\b',str(r.excerpt),re.I) and not re.search(
       r'\b(no|not|unavailable|planned|referred)\b',str(r.excerpt),re.I):
        add(r.facility_id,r.service,'website_lists_service')
    if r.source_type in ('news_report','web_search') and r.service in SERVICES:
        for field,pattern in [('report_interrupted',r'interrupt|halt|unavailable|not installed|closed'),
                              ('report_planned',r'planned|proposed|tender'),('report_delivered',r'underwent|performed|patients received|resumed')]:
            if re.search(pattern,str(r.excerpt),re.I):
                dated_feature(r.facility_id,r.service,max(str(r.event),str(r.published)),field,r.url)
                break

external = read('external_evidence_ext',[c for c in sorted(schemas['external_evidence_ext']) if c != 'source_quote']).fillna('')
stage_feature = {'interrupted':'report_interrupted','reported_unavailable':'report_interrupted',
                 'reported_not_installed':'report_interrupted','planned':'report_planned',
                 'resumed':'report_delivered','care_delivered_described':'report_delivered'}
for r in external.sort_values('evidence_id').itertuples():
    if r.match_status != 'matched' or (r.service,url_key(r.source_url)) in label_urls:
        continue
    if r.evidence_class == 'hospital_page' and r.care_stage == 'service_listed' and r.fact_type != 'provided_elsewhere':
        add(r.matched_facility_id,r.service,'website_lists_service')
    if r.evidence_class == 'news_report' and r.care_stage in stage_feature:
        dated_feature(r.matched_facility_id,r.service,max(str(r.event_date),str(r.publication_date)),stage_feature[r.care_stage],r.source_url)
for (identifier,service),(_,feature,_) in sorted(dated.items()):
    add(identifier,service,feature)
nabh = set(reviewed.loc[reviewed.review_status.eq('reviewed') & reviewed.source_type.eq('nabh'),'facility_id'])
for identifier,service in sorted(set(pair_features) | set(zip(gold.facility_id,gold.service))):
    if identifier in nabh:
        add(identifier,service,'on_nabh')
    if by_id.at[identifier,'location_conflict']:
        add(identifier,service,'location_conflict')

def same_gold_source(identifier,service):
    entry = by_id.loc[identifier]
    try:
        urls = json.loads(entry.source_urls)
    except (ValueError,TypeError):
        urls = []
    if not isinstance(urls,list):
        urls = []
    return any((service,url_key(u)) in label_urls for u in urls if u)

if label_urls:
    for (identifier,service),values in pair_features.items():
        if same_gold_source(identifier,service):
            values.difference_update(FAMILIES['virtue_claim']+FAMILIES['virtue_detail'])

feature_rows = [(i,s,k,int(k in values)) for (i,s),values in sorted(pair_features.items()) for k in FEATURES]
write('evidence_features',feature_rows,'facility_id string, service string, feature string, value int')
feature_counts = pd.DataFrame(feature_rows,columns=['facility_id','service','feature','value'])
print('Present features per service')
print(feature_counts.pivot_table(index='feature',columns='service',values='value',aggfunc='sum',fill_value=0).reindex(FEATURES).fillna(0).astype(int))

def matrix(frame, features=None):
    features = pair_features if features is None else features
    return np.array([[int(k in features.get((i,s),set())) for k in FEATURES]
                     for i,s in zip(frame.facility_id,frame.service)],dtype=np.float64).reshape(len(frame),len(FEATURES))

def fit_bayes(train,m,features=None):
    x, y = matrix(train,features),train.y.to_numpy(dtype=int)
    group_counts = train.groupby('group').y.agg(['sum','count'])
    mean = float(y.mean())
    priors = ((group_counts['sum'] + m*mean) / (group_counts['count']+m)).to_dict()
    pos,neg = x[y==1],x[y==0]
    lr = ((pos.sum(axis=0)+1)/(len(pos)+2))/((neg.sum(axis=0)+1)/(len(neg)+2))
    return mean,priors,np.log(lr),pos,neg

def predict_bayes(model, frame, features=None):
    mean,priors,loglr,*_ = model
    p0 = np.clip(frame.group.map(priors).fillna(mean).to_numpy(dtype=float),.01,.99)
    x = matrix(frame,features)
    chosen = np.zeros_like(x)
    for keys in FAMILIES.values():
        order = sorted((FEATURES.index(k) for k in keys),key=lambda j:(-abs(loglr[j]),j))
        is_present = x[:,order].astype(bool)
        has_feature = is_present.any(axis=1)
        indices = np.asarray(order)[is_present.argmax(axis=1)]
        chosen[np.flatnonzero(has_feature),indices[has_feature]] = loglr[indices[has_feature]]
    return np.clip(expit(logit(p0)+chosen.sum(axis=1)),.01,.99),p0,chosen

def folds(frame,n,seed=SEED):
    if len(frame) < n or frame.district_key.nunique() < n or frame.y.nunique() != 2:
        return []
    splitter = StratifiedGroupKFold(n_splits=n,shuffle=True,random_state=seed)
    parts = list(splitter.split(frame,frame.y,frame.district_key))
    return parts if all(frame.iloc[t].y.nunique()==2 and len(v) for t,v in parts) else []

def calibration(train,m,n=3):
    splits = folds(train,n)
    if not splits:
        return None
    raw,trial = np.zeros(len(train)),np.zeros(len(train))
    for tr,va in splits:
        raw[va] = predict_bayes(fit_bayes(train.iloc[tr],m),train.iloc[va])[0]
    y = train.y.to_numpy()
    for tr,va in splits:
        iso = IsotonicRegression(out_of_bounds='clip').fit(raw[tr],y[tr])
        trial[va] = calibrated(iso,raw[va])
    if probability_metrics(y,trial)[0] >= probability_metrics(y,raw)[0]:
        return None
    return IsotonicRegression(out_of_bounds='clip').fit(raw,y)

def calibrated(model,values):
    return np.clip(model.predict(values),.01,.99) if model is not None else values

def probability_metrics(y,p):
    return float(np.mean((y-p)**2)),float(-np.mean(y*np.log(p)+(1-y)*np.log1p(-p)))

gold = gold.merge(fac[['facility_id','group','latitude','longitude','location_conflict']],on='facility_id',how='left')
gold['district_key'] = gold.state + '/' + gold.district
eligible, oof_rows, reliability_rows, lr_rows, posterior_rows = {}, [], [], [], []
full_models = {}
for service in SERVICES:
    labelled = gold.loc[gold.service.eq(service) & gold.district.ne('') & gold.state.ne('')
                         & gold.label_rule.ne('pmndp_complete_state_absence')].reset_index(drop=True)
    if min((labelled.y==0).sum(),(labelled.y==1).sum()) < MIN_CLASS or not folds(labelled,5):
        print(f'INSUFFICIENT LABELS · {service}: {int((labelled.y==1).sum())} positive, {int((labelled.y==0).sum())} negative with resolved districts; need {MIN_CLASS} each and five viable district folds.')
        continue
    eligible[service] = labelled
    raw, calibrated_oof, logistic = (np.full(len(labelled),np.nan) for _ in range(3))
    group_dummy = pd.get_dummies(labelled.group,dtype=float).to_numpy()
    design = np.column_stack([matrix(labelled),group_dummy])
    for tr,va in folds(labelled,5):
        train,hold = labelled.iloc[tr],labelled.iloc[va]
        assert not set(train.district_key) & set(hold.district_key)
        raw[va] = predict_bayes(fit_bayes(train,DEFAULT['m']),hold)[0]
        calibrated_oof[va] = calibrated(calibration(train,DEFAULT['m']),raw[va])
        inner = folds(train,3)
        if inner:
            # Explicit inner indices ensure the same grouped splits for tuning.
            model = GridSearchCV(LogisticRegression(max_iter=1000,random_state=SEED),
                                 {'C':[.01,.1,1,10]},scoring='neg_log_loss',cv=inner,error_score=np.nan)
            if all(train.iloc[v].y.nunique()==2 for _,v in inner):
                model.fit(design[tr],train.y)
                logistic[va] = np.clip(model.predict_proba(design[va])[:,1],.01,.99)
    y = labelled.y.to_numpy()
    for method,p in [('bayes_raw',raw),('bayes_isotonic_nested',calibrated_oof),('logistic_l2',logistic)]:
        if not np.isfinite(p).all():
            print(f'{service} {method}: insufficient viable inner folds')
            continue
        brier,loss = probability_metrics(y,p)
        oof_rows.append((service,method,brier,loss,len(y)))
        for bin_index,group in pd.DataFrame({'p':p,'y':y,'bin':np.minimum(9,(p*10).astype(int))}).groupby('bin'):
            reliability_rows.append((service,method,int(bin_index),float(group.p.mean()),float(group.y.mean()),len(group)))
        print(service,method,'OOF Brier',round(brier,5),'log loss',round(loss,5))
    # Include valid labels without a resolved district in the final serving fit only.
    # Rule-derived negatives are recorded but omitted from fitting and evaluation: their rule uses the predictor.
    all_labels = gold.loc[gold.service.eq(service) & gold.label_rule.ne('pmndp_complete_state_absence')].reset_index(drop=True)
    model = fit_bayes(all_labels,DEFAULT['m'])
    iso = calibration(labelled,DEFAULT['m'],n=5)
    full_models[service] = model,iso,iso is not None
    _,_,loglr,pos,neg = model
    rng = np.random.default_rng(SEED)
    # Each facility contributes once per service. Stratified resampling preserves class counts.
    pos_weights = rng.multinomial(len(pos),np.full(len(pos),1/len(pos)),size=1000)
    neg_weights = rng.multinomial(len(neg),np.full(len(neg),1/len(neg)),size=1000)
    boot = np.log(((pos_weights@pos+1)/(len(pos)+2))/((neg_weights@neg+1)/(len(neg)+2)))
    low,high = np.exp(np.quantile(boot,[.025,.975],axis=0))
    ci_family = {k:f for f,items in FAMILIES.items() for k in items}
    for ix,k in enumerate(FEATURES):
        lr_rows.append((service,ci_family[k],k,float(np.exp(loglr[ix])),float(low[ix]),float(high[ix]),len(pos),len(neg)))

VERSION = 'atlas-etc-v1-' + hashlib.sha256(json.dumps({
    'gold':gold_rows,'features':feature_rows,'assumptions':ASSUMPTIONS},sort_keys=True).encode()).hexdigest()[:12]
# Dataset-derived effective model date keeps reruns on identical inputs reproducible.
effective_date = max((date_value(r[-1]).date().isoformat() for r in gold_rows),default=None)
for service,(model,iso,_) in full_models.items():
    identifiers = sorted(i for i,s in pair_features if s==service)
    frame = by_id.loc[identifiers,['group','latitude','longitude','location_conflict']].reset_index()
    frame['service'] = service
    pred,p0,contributions = predict_bayes(model,frame)
    pred = calibrated(iso,pred)
    for idx,r in enumerate(frame.itertuples()):
        active = {FEATURES[j]:float(contributions[idx,j]) for j in range(len(FEATURES)) if contributions[idx,j]}
        strongest = sorted(active,key=lambda k:(-abs(active[k]),k))[:3]
        reasons = [f'{REASONS[k]} (×{np.exp(active[k]):.2f})' for k in strongest]
        lat = float(r.latitude) if np.isfinite(r.latitude) else None
        lon = float(r.longitude) if np.isfinite(r.longitude) else None
        posterior_rows.append((r.facility_id,service,float(p0[idx]),float(pred[idx]),active,reasons,VERSION,
                               effective_date,lat,lon,bool(r.location_conflict)))
write('lr_table',lr_rows,'service string, family string, feature string, lr double, lr_ci_low double, lr_ci_high double, n_pos int, n_neg int')
write('facility_posterior',posterior_rows,'facility_id string, service string, p0 double, p double, logit_contributions map<string,double>, top_reasons array<string>, model_version string, scored_at string, latitude double, longitude double, location_conflict boolean')
write('calibration_metrics',oof_rows,'service string, method string, brier double, log_loss double, n_labels int')
write('calibration_reliability',reliability_rows,'service string, method string, bin int, mean_predicted double, observed_rate double, n int')
print('Posterior sanity:',len(posterior_rows),'rows, all finite and clipped:',all(.01<=r[3]<=.99 for r in posterior_rows))

# COMMAND ----------

# MAGIC %md
# MAGIC ## C. Expected time to care
# MAGIC Travel uses haversine distance, a detour factor and average road speed. The fixed start overhead is applied to each modelled leg, as in the specified travel function. With two options, add the expected time lost at the first site, travel to its best backup, and the expected penalty if the backup also cannot provide care.

# COMMAND ----------

def haversine(a,b):
    a,b = np.radians(a),np.radians(b)
    lat = (b[...,0]-a[...,0])/2
    lon = (b[...,1]-a[...,1])/2
    return 12742*np.arcsin(np.sqrt(np.clip(np.sin(lat)**2 + np.cos(a[...,0])*np.cos(b[...,0])*np.sin(lon)**2,0,1)))

def etc_values(km,between,p,settings):
    factor = 60*settings['kappa']/settings['v']
    start = factor*km+settings['t0']
    if len(p) == 1:
        return start+(1-p)*settings['H'],np.array([-1]),start
    onward = factor*between+settings['t0']+(1-p)[None,:]*settings['H']
    np.fill_diagonal(onward,np.inf)
    backup = onward.argmin(axis=1)
    return start+(1-p)*(settings['h']+onward[np.arange(len(p)),backup]),backup,start

def order_for(etc,p,km,ids):
    return np.lexsort((ids,km,-p,etc))

def rank_frame(frame,origin,settings, radius=True):
    frame = frame.loc[~frame.location_conflict & frame.latitude.between(6,38) & frame.longitude.between(68,98)].copy()
    coords = frame[['latitude','longitude']].to_numpy(dtype=float)
    km = haversine(np.asarray(origin),coords)
    if radius:
        usable = km<=100
        frame,coords,km = frame.iloc[usable].copy(),coords[usable],km[usable]
    if not len(frame):
        return frame
    between = haversine(coords[:,None,:],coords[None,:,:])
    p,ids = frame.p.to_numpy(),frame.facility_id.to_numpy()
    etc,backup,start = etc_values(km,between,p,settings)
    frame['km'],frame['etc_min'] = km,etc
    frame['backup'] = [ids[idx] if idx>=0 else None for idx in backup]
    frame['voi_min'] = call_values(km,between,p,etc,start,ids,settings)
    return frame.iloc[order_for(etc,p,km,ids)]

# COMMAND ----------

# MAGIC %md
# MAGIC ## D. Value of one phone call
# MAGIC A call is modelled as revealing whether the selected facility can provide care. For each of the first five options, compare the current best ETC with the probability-weighted YES and NO scenarios. The NO branch removes the facility both as a first stop and as a backup. Floor the gain at zero. Recommend the highest-value call only when its gain exceeds the cost. Call reliability is an extension.

# COMMAND ----------

def call_values(km,between,p,etc,start,ids,settings):
    values = np.zeros(len(p))
    best = etc.min()
    for index in order_for(etc,p,km,ids)[:5]:
        rest = np.arange(len(p)) != index
        without = etc_values(km[rest],between[np.ix_(rest,rest)],p[rest],settings)[0].min() if rest.any() else settings['H']
        values[index] = max(0.,best-(p[index]*start[index]+(1-p[index])*without))
    return values

def call_first(ranked,settings):
    if ranked.empty:
        return None
    selection = ranked.sort_values('voi_min',ascending=False,kind='stable').iloc[0]
    return selection.facility_id if selection.voi_min > settings['c_call'] else None

print('ETC sanity · identical pins:',float(haversine(np.array([20.,75.]),np.array([20.,75.]))))
print('VOI sanity · no calls can have negative value by construction; recommendations strictly exceed the call cost.')

# COMMAND ----------

# MAGIC %md
# MAGIC ## E. Held-out evaluation
# MAGIC A district is the unit of separation. Facilities from held-out districts are excluded from all fitting, including calibration and logistic tuning. Each labelled facility seeds a district-centred search. We collapse identical district-service queries before inference because they have identical candidates and answers. Each candidate must carry a held-out label, be within 100 km and have a usable location. Queries need at least one labelled positive.
# MAGIC
# MAGIC Travel is replayed against gold labels. Every false stop incurs the modelled turn-away cost. The reported minutes are simulated using the declared travel assumptions. We report per-service 95% percentile intervals and a two-sided paired sign-flip test with 10,000 draws each.
# MAGIC The leakage diagnostic refits on shuffled training labels while preserving held-out truth. A statistically significant sham gain is flagged for inspection. It may also occur by chance or when the ETC structure alone helps.

# COMMAND ----------

def legacy_priority(identifier,service):
    claim = legacy.get((identifier,service))
    if claim is None:
        return (0,2)
    kind,subtype,conflict = claim
    tier = -1 if conflict or kind in ('explicit_absence','offsite_referral','planned') else 0
    scope = 2 if kind!='explicit_onsite' else int((service=='c_section' and subtype!='emergency_obstetric_capability')
                 or subtype in ('sncu_level2','stabilization_documented'))
    return (-tier,scope)

legacy = {(r.facility_id,r.service):(r.best_claim_type,r.best_claim_subtype,bool(r.has_conflicting_evidence))
          for r in claims.itertuples()}

def sham_frame(train,rng):
    shuffled = train.copy()
    shuffled['y'] = rng.permutation(train.y.to_numpy())
    return shuffled

def make_searches(labelled, m, shuffle=False):
    rng = np.random.default_rng(SEED)
    searches = []
    for tr,va in folds(labelled,5):
        train,hold = labelled.iloc[tr],labelled.iloc[va].copy()
        if shuffle:
            train = sham_frame(train,rng)
        service = hold.service.iloc[0]
        raw = predict_bayes(fit_bayes(train,m),hold)[0]
        hold['p'] = calibrated(calibration(train,m),raw)
        hold = hold.loc[~hold.location_conflict & hold.latitude.between(6,38) & hold.longitude.between(68,98)].reset_index(drop=True)
        coords = hold[['latitude','longitude']].to_numpy(dtype=float)
        for state,district in labelled.iloc[va][['state','district']].drop_duplicates().sort_values(['state','district']).itertuples(index=False,name=None):
            if (state,district) not in centres.index:
                continue
            origin = centres.loc[(state,district)].to_numpy(dtype=float)
            distances = haversine(origin,coords)
            mask = distances<=100
            members = hold.loc[mask]
            if not members.y.eq(1).any():
                continue
            xy = coords[mask]
            ids = members.facility_id.to_numpy()
            priorities = np.asarray([legacy_priority(i,service) for i in ids])
            searches.append((state,district,distances[mask],haversine(xy[:,None,:],xy[None,:,:]),
                             members.p.to_numpy(),members.y.to_numpy(dtype=int),ids,priorities))
    return searches

METRICS = ('mrr','ndcg_at_3','realised_minutes')
RANKERS = ('distance','current_tiers','posterior','etc')

def realised_minutes(order,km,between,y,settings):
    factor = 60*settings['kappa']/settings['v']
    minutes = 0.
    previous = None
    for index in order:
        minutes += factor*(km[index] if previous is None else between[previous,index])+settings['t0']
        if y[index]:
            return minutes
        minutes += settings['h']
        previous = index
    return minutes+settings['H']

def scores(order,km,between,y,settings):
    rel = y[order]
    hit = np.flatnonzero(rel)
    discounts = 1/np.log2(np.arange(2,5))
    dcg = rel[:3]@discounts[:min(3,len(rel))]
    ideal = discounts[:min(3,int(y.sum()))].sum()
    return 1/(1+hit[0]) if len(hit) else 0.,float(dcg/ideal) if ideal else 0.,realised_minutes(order,km,between,y,settings)

def evaluate(searches, settings):
    output = {name:[] for name in RANKERS}
    picks = 0
    for _,_,km,between,p,y,ids,priorities in searches:
        etc,_,start = etc_values(km,between,p,settings)
        orders = (np.lexsort((ids,km)),np.lexsort((ids,km,priorities[:,1],priorities[:,0])),
                  np.lexsort((ids,km,-p)),order_for(etc,p,km,ids))
        for name,order in zip(RANKERS,orders):
            output[name].append(scores(order,km,between,y,settings))
        picks += int(call_values(km,between,p,etc,start,ids,settings).max()>settings['c_call'])
    return {k:np.array(v,dtype=float).reshape(-1,3) for k,v in output.items()},picks

def inference(values, sign_flip=False):
    rng = np.random.default_rng(SEED)
    n = len(values)
    observed = float(values.mean())
    sampled, extremes = [],0
    for _ in range(20):
        sampled.append(values[rng.integers(0,n,size=(500,n))].mean(axis=1))
        if sign_flip:
            signs = 2*rng.integers(0,2,size=(500,n))-1
            extremes += int((np.abs(signs@values/n)>=abs(observed)-1e-12).sum())
    low,high = np.quantile(np.concatenate(sampled),[.025,.975])
    return observed,float(low),float(high),(extremes+1)/10001 if sign_flip else None

results_rows, tests_rows, sensitivity_rows, shuffle_rows, headlines = [],[],[],[],[]
searches_by_service = {}
for service,labelled in eligible.items():
    searches = make_searches(labelled,DEFAULT['m'])
    searches_by_service[service] = searches
    n = len(searches)
    if n < MIN_SEARCHES:
        print(f'INSUFFICIENT SEARCHES · {service}: {n} distinct district origins after cohort filtering; need {MIN_SEARCHES}.')
        continue
    evaluation,picks = evaluate(searches,DEFAULT)
    print(service,n,'held-out search queries, recommended calls',picks)
    for ranker, values in evaluation.items():
        for j, metric in enumerate(METRICS):
            mean,low,high,_ = inference(values[:,j])
            results_rows.append((service,ranker,metric,mean,low,high,n))
    for j,metric in enumerate(METRICS):
        diff = evaluation['etc'][:,j]-evaluation['distance'][:,j]
        mean,low,high,p_value = inference(diff,True)
        tests_rows.append((service,'etc_minus_distance',metric,mean,low,high,p_value,n))
        if metric == 'realised_minutes':
            headlines.append({'service':service,'n_searches':n,'minutes_saved':-mean,'ci_low':-high,'ci_high':-low,'p_value':p_value})
            print(f'{service}: {n} held-out searches, {-mean:.2f} minutes saved (95% CI {-high:.2f} to {-low:.2f}), p={p_value:.5f}')
    shuffled,picks_sham = evaluate(make_searches(labelled,DEFAULT['m'],shuffle=True),DEFAULT)
    sham_diff = shuffled['distance'][:,2]-shuffled['etc'][:,2]
    mean,lo,hi,p_value = inference(sham_diff,True)
    leakage_flag = mean>0 and p_value<.05
    shuffle_rows.append((service,mean,lo,hi,p_value,leakage_flag))
    print('Shuffled training labels:',service,mean,'minutes saved, p=',p_value,
          '· investigate above-chance gain' if leakage_flag else '· no significant gain')

    grid = itertools.product(ASSUMPTIONS['kappa'][1],[20,30,40],[15,30,60])
    variants = [('travel_grid',dict(DEFAULT,kappa=k,v=v,h=h)) for k,v,h in grid]
    variants += [(parameter,dict(DEFAULT,**{parameter:value})) for parameter in ('t0','H','c_call','m')
                 for value in ASSUMPTIONS[parameter][1]]
    for axis,settings in variants:
        batch = searches if settings['m']==DEFAULT['m'] else make_searches(labelled,settings['m'])
        res,calls = evaluate(batch,settings)
        diff = res['distance'][:,2]-res['etc'][:,2]
        mean,lo,hi,p_value = inference(diff,True)
        sensitivity_rows.append((service,axis,*[float(settings[k]) for k in ('kappa','v','t0','h','H','c_call','m')],
                                 mean,lo,hi,p_value,len(batch),calls))
    cells = [r for r in sensitivity_rows if r[0]==service and r[1]=='travel_grid']
    print(service,'positive estimated minutes saved in',sum(r[9]>0 for r in cells),'of',len(cells),'travel-grid runs')

write('eval_results',results_rows,'service string, ranker string, metric string, value double, ci_low double, ci_high double, n_searches int')
write('eval_tests',tests_rows,'service string, comparison string, metric string, mean_diff double, ci_low double, ci_high double, p_value double, n_searches int')
write('sensitivity_results',sensitivity_rows,'service string, axis string, kappa double, v double, t0 double, h double, H_penalty double, c_call double, m double, minutes_saved double, ci_low double, ci_high double, p_value double, n_searches int, n_call_recommendations int')
write('shuffle_diagnostic',shuffle_rows,'service string, minutes_saved double, ci_low double, ci_high double, p_value double, investigate boolean')

# COMMAND ----------

# MAGIC %md
# MAGIC ## F. Sanity cases and model card
# MAGIC The published examples are checked independently from the held-out evaluation. A current posterior cannot be passed off as a February 2024 prediction. The historical example checks the archived evidence, and reports biological service scope rather than present-day acceptance.

# COMMAND ----------

scenarios = {r.scenario:json.loads(r.payload) for r in spark.table(tables['frontend_scenarios']).select('scenario','payload').collect()}
palwal = scenarios.get('palwal',{})
bhagalpur = scenarios.get('bhagalpur',{})
case_rows = []
def position(scenario,group,needle):
    return next((i for i,v in enumerate(scenario.get(group,[]),start=1) if needle in v['name'].lower()),None)

palwal_pass = position(palwal,'supported','jindal') == 1 and position(palwal,'exclusions','civil') is not None
bhagalpur_pass = bhagalpur.get('cutoff') == '2024-02-18' and position(bhagalpur,'supported','mayaganj') == 1
case_rows.extend([('Palwal MRI','archived evidence',palwal_pass,'Jindal first, Civil Hospital withheld'),
                  ('Bhagalpur dialysis','2024-02-18 archived evidence',bhagalpur_pass,'Mayaganj first in the archived replay')])
if 'mri' in full_models:
    current = pd.DataFrame([(r[0],r[3],r[8],r[9],r[10]) for r in posterior_rows if r[1]=='mri'],
                           columns=['facility_id','p','latitude','longitude','location_conflict'])
    origin = (read('city_origins').loc[lambda t:t.origin_city.map(norm).eq('palwal') & t.state.map(norm).eq('haryana')])
    if not origin.empty:
        ranked = rank_frame(current,origin.iloc[0][['origin_latitude','origin_longitude']].to_numpy(dtype=float),DEFAULT)
        ids = ranked.facility_id.tolist()
        jindal,civil = '050479fe-82a8-404b-a41b-a61d15eb9577','a948a2d7-b57a-4df6-b082-d8e5b86a214b'
        passed = jindal in ids and civil in ids and ids.index(jindal)<ids.index(civil)
        case_rows.append(('Palwal MRI','fitted ETC',passed,f'Jindal and Civil ETC positions: {[ids.index(i)+1 if i in ids else None for i in (jindal,civil)]}'))
else:
    case_rows.append(('Palwal MRI','fitted ETC',None,'Insufficient gold labels for MRI'))
cutoff = date_value('2024-02-18')
historical_labels = gold.loc[gold.service.eq('dialysis') & gold.label_rule.ne('pmndp_complete_state_absence')
                             & gold.date.map(date_value).le(cutoff)]
history = {(i,s): {max(observations)[1]} for (i,s),entries in dated_history.items() if s=='dialysis'
           if (observations := [entry for entry in entries if entry[0]<=cutoff])}
if min((historical_labels.y==0).sum(),(historical_labels.y==1).sum()) >= MIN_CLASS and history:
    origin = read('city_origins').loc[lambda t:t.origin_city.map(norm).eq('bhagalpur') & t.state.map(norm).eq('bihar')]
    if origin.empty:
        case_rows.append(('Bhagalpur dialysis','fitted historical ETC',None,'Bhagalpur origin missing'))
    else:
        frame = by_id.loc[sorted(i for i,s in history),['group','latitude','longitude','location_conflict']].reset_index()
        frame['service'] = 'dialysis'
        frame['p'] = predict_bayes(fit_bayes(historical_labels,DEFAULT['m'],history),frame,history)[0]
        ranked = rank_frame(frame,origin.iloc[0][['origin_latitude','origin_longitude']].to_numpy(dtype=float),DEFAULT)
        first = ranked.facility_id.iloc[0] if not ranked.empty else None
        case_rows.append(('Bhagalpur dialysis','fitted historical ETC',first=='29903d8a-3433-4240-b1eb-91094a7551d4',
                          'Historical fit uses dated reports and labels at the cutoff, with present directory geography'))
else:
    case_rows.append(('Bhagalpur dialysis','fitted historical ETC',None,'Insufficient pre-cutoff gold labels or published evidence'))
display(write('ranking_sanity_cases',case_rows,'example string, method string, passed boolean, detail string'))
counts_by_service = {s: {'negative':int(counts.loc[s,0]),'positive':int(counts.loc[s,1])} for s in SERVICES}
status = 'evaluated' if headlines else ('trained_without_evaluation' if full_models else 'insufficient_gold_labels')
display(write('model_card',[(VERSION,effective_date,status,json.dumps(counts_by_service,sort_keys=True),
                             json.dumps(oof_rows),json.dumps(headlines),json.dumps(ASSUMPTIONS),json.dumps(sorted(full_models)))],
    'model_version string, trained_at string, status string, n_labels string, brier string, headline string, assumptions string, trained_services string'))
display(spark.table(f'{OUT}.eval_tests'))
if not headlines:
    print('No evaluable headline yet. Upload verified gold CSVs with at least 30 positives and 30 negatives per service and coverage across at least 30 eligible district queries.')
for h in headlines:
    print(f"On {h['n_searches']} held-out {h['service']} searches, ranking by expected time to care was estimated to save "
          f"{h['minutes_saved']:.2f} minutes versus distance-only (95% CI {h['ci_low']:.2f} to {h['ci_high']:.2f}, p={h['p_value']:.5f}).")
