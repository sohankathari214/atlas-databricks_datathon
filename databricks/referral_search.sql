CREATE OR REPLACE FUNCTION workspace.referral_verification.search_referrals(query_location STRING, query_service STRING)
RETURNS TABLE (payload STRING)
COMMENT 'Resolve an Indian locality, district, PIN or coordinates and compare Virtue services and care settings against campus evidence.'
RETURN
WITH input AS (
  SELECT trim(query_location) raw_location,
    regexp_replace(lower(trim(query_location)), r'\s+', ' ') normalized_location,
    lower(trim(split_part(query_location, ',', 1))) locality,
    lower(trim(split_part(query_location, ',', 2))) region
), postal AS (
  SELECT lower(trim(regexp_replace(officename, r'(?i)\s+(S\.?O\.?|B\.?O\.?|H\.?O\.?)$', ''))) office,
    lower(trim(district)) district, lower(trim(statename)) state, cast(pincode AS STRING) pin,
    try_cast(latitude AS DOUBLE) lat, try_cast(longitude AS DOUBLE) lon
  FROM databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.india_post_pincode_directory
), pin_points AS (
  SELECT state, lat, lon FROM postal CROSS JOIN input
  WHERE pin=raw_location AND lat BETWEEN 6 AND 38 AND lon BETWEEN 68 AND 98
), pin_density AS (
  SELECT a.state,a.lat anchor_lat,a.lon anchor_lon,median(b.lat) lat,median(b.lon) lon,count(*) votes
  FROM (SELECT DISTINCT state,lat,lon FROM pin_points) a JOIN pin_points b
    ON a.state=b.state AND abs(a.lat-b.lat)<=0.25 AND abs(a.lon-b.lon)<=0.25
  GROUP BY a.state,a.lat,a.lon
  HAVING count(*) >= (SELECT count(*)/2.0 FROM pin_points)
), pin_winner AS (
  SELECT * FROM pin_density ORDER BY votes DESC, state, anchor_lat, anchor_lon LIMIT 1
), pin_cluster AS (
  SELECT w.* FROM pin_winner w WHERE NOT EXISTS (
    SELECT 1 FROM pin_density competing WHERE competing.votes = w.votes
      AND (competing.state <> w.state OR abs(competing.lat-w.lat)>0.4 OR abs(competing.lon-w.lon)>0.4)
  )
), geo AS (
  SELECT 'City centre' method, lower(trim(origin_city)) place, lower(trim(state)) state,
    cast(origin_latitude AS DOUBLE) lat, cast(origin_longitude AS DOUBLE) lon, 1 priority
  FROM workspace.referral_verification.city_origins CROSS JOIN input
  WHERE lower(trim(origin_city)) = locality AND (region = '' OR lower(trim(state)) = region)
  UNION ALL
  SELECT 'Virtue city centre', lower(trim(g.city)), lower(trim(g.state)), median(g.latitude), median(g.longitude), 2
  FROM workspace.referral_verification.facility_location_flags g CROSS JOIN input
  WHERE lower(trim(g.city)) = locality AND (region = '' OR lower(trim(g.state)) = region)
    AND NOT g.distance_ranking_withheld AND g.latitude BETWEEN 6 AND 38 AND g.longitude BETWEEN 68 AND 98
  GROUP BY 2,3 HAVING (percentile_approx(g.latitude,0.75)-percentile_approx(g.latitude,0.25)) < 0.55
    AND (percentile_approx(g.longitude,0.75)-percentile_approx(g.longitude,0.25)) < 0.55
  UNION ALL
  SELECT 'India Post locality centroid', office, state, median(lat), median(lon), 3
  FROM postal CROSS JOIN input
  WHERE ((office = locality AND (region = '' OR state = region OR district = region))
         OR (region = '' AND concat_ws(' ', office, district) = normalized_location))
    AND lat BETWEEN 6 AND 38 AND lon BETWEEN 68 AND 98
  GROUP BY office,state HAVING (max(lat)-min(lat)) < 0.65 AND (max(lon)-min(lon)) < 0.65
  UNION ALL
  SELECT 'India Post district centroid', district, state, median(lat), median(lon), 4
  FROM postal CROSS JOIN input WHERE district = locality AND (region = '' OR state = region)
    AND lat BETWEEN 6 AND 38 AND lon BETWEEN 68 AND 98
  GROUP BY district,state
  UNION ALL
  SELECT 'India Post PIN centroid', raw_location, state, lat, lon, 0
  FROM pin_cluster CROSS JOIN input
  UNION ALL
  SELECT 'Entered coordinates', raw_location, '', try_cast(locality AS DOUBLE),try_cast(region AS DOUBLE),0
  FROM input WHERE raw_location RLIKE r'^[0-9]+(\.[0-9]+)?\s*,\s*[0-9]+(\.[0-9]+)?$'
    AND try_cast(locality AS DOUBLE) BETWEEN 6 AND 38 AND try_cast(region AS DOUBLE) BETWEEN 68 AND 98
), matches AS (
  SELECT * FROM geo WHERE lat BETWEEN 6 AND 38 AND lon BETWEEN 68 AND 98
), origin AS (
  SELECT * FROM matches
  WHERE (SELECT count(DISTINCT state) FROM matches) = 1
  ORDER BY priority, state LIMIT 1
), routing_pattern AS (
  SELECT CASE WHEN query_service='emergency_care'
      THEN r'(?i)\b(emergency departments?|emergency rooms?|emergency medicine|accident and emergency|24[ -]hour emergency|24/7 emergency|casualty department)\b'
      ELSE r'(?i)\b(general medicine|general practice|family medicine|outpatient departments?|general physicians?|primary care)\b'
    END pattern
), catalog AS (
  SELECT c.facility_id id, c.facility_name name, c.city, c.state, c.latitude, c.longitude,
    c.best_claim_type claim_type, c.best_claim_subtype claim_subtype, c.best_claim_source_field claim_field, c.best_claim_excerpt excerpt,
    c.has_conflicting_evidence claim_conflict, c.virtue_source_urls source_urls,
    g.location_flags, coalesce(g.distance_ranking_withheld,false) loc_conflict,
    concat_ws(', ', f.address_line1, f.address_line2, c.city, c.state, c.pin) address,
    f.officialWebsite website, f.facebookLink facebook,
    CASE WHEN trim(f.officialPhone) RLIKE r'^\+?[0-9][0-9 ()-]{7,17}[0-9]$'
      THEN regexp_replace(trim(f.officialPhone),'[^+0-9]','') END phone
  FROM workspace.referral_verification.v_service_best_claims c
  LEFT JOIN workspace.referral_verification.facility_location_flags g ON c.unique_id = g.unique_id
  LEFT JOIN databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities f ON c.unique_id = f.unique_id
  WHERE c.service = query_service
  UNION ALL
  SELECT x.unique_id, x.name, x.address_city, x.address_stateOrRegion,
    try_cast(x.latitude AS DOUBLE), try_cast(x.longitude AS DOUBLE),
    'care_setting_mention', NULL, hit.field, hit.excerpt, false, x.source_urls,
    g.location_flags, coalesce(g.distance_ranking_withheld,false),
    concat_ws(', ',x.address_line1,x.address_line2,x.address_city,x.address_stateOrRegion,x.address_zipOrPostcode),
    x.officialWebsite,x.facebookLink,
    CASE WHEN trim(x.officialPhone) RLIKE r'^\+?[0-9][0-9 ()-]{7,17}[0-9]$'
      THEN regexp_replace(trim(x.officialPhone),'[^+0-9]','') END
  FROM databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities x
  LEFT JOIN workspace.referral_verification.facility_location_flags g ON x.unique_id=g.unique_id
  CROSS JOIN routing_pattern term
  CROSS JOIN LATERAL (
    SELECT try_element_at(filter(array(
      named_struct('field','description','excerpt',regexp_extract(x.description,concat(r'[^"\n.!?]{0,70}',term.pattern,r'[^"\n.!?]{0,95}'),0)),
      named_struct('field','capability','excerpt',regexp_extract(x.capability,concat(r'[^"\n.!?]{0,70}',term.pattern,r'[^"\n.!?]{0,95}'),0)),
      named_struct('field','specialties','excerpt',regexp_extract(x.specialties,term.pattern,0))
    ), claim -> length(claim.excerpt)>0),1) hit
  ) matched
  WHERE query_service IN ('emergency_care','primary_care') AND hit.excerpt IS NOT NULL
    AND NOT hit.excerpt RLIKE r'(?i)\b(not available|no\s+(on-site\s+)?emergency|no emergency|no outpatient|does not (offer|provide)|planned only|refers patients)\b'
), distances AS (
  SELECT c.*, 12742 * asin(sqrt(least(1D, pow(sin(radians(c.latitude-o.lat)/2),2)
    + cos(radians(o.lat))*cos(radians(c.latitude))*pow(sin(radians(c.longitude-o.lon)/2),2)))) raw_km
  FROM catalog c CROSS JOIN origin o
  WHERE c.latitude BETWEEN 6 AND 38 AND c.longitude BETWEEN 68 AND 98
    AND abs(c.latitude-o.lat) < 1.4 AND abs(c.longitude-o.lon) < 2
), ranked AS (
  SELECT *, row_number() OVER (PARTITION BY loc_conflict ORDER BY raw_km,name,id) position,
    CASE WHEN loc_conflict THEN -3 WHEN claim_conflict OR claim_type IN ('explicit_absence','offsite_referral','planned') THEN -1 ELSE 0 END tier
  FROM distances WHERE raw_km <= 100
), sorted AS (
  SELECT *, row_number() OVER (PARTITION BY tier ORDER BY CASE WHEN claim_type <> 'explicit_onsite' THEN 2
      WHEN query_service = 'c_section' AND coalesce(claim_subtype,'') <> 'emergency_obstetric_capability' THEN 1
      WHEN claim_subtype IN ('sncu_level2','stabilization_documented') THEN 1 ELSE 0 END, raw_km,name,id) evidence_position
  FROM ranked
), signals AS (
  SELECT facility_id, collect_list(named_struct('publisher',publisher,'url',url,'event',event,'published',published,
    'checked',checked,'excerpt',excerpt,'translation','','rationale',rationale,'kind',source_type)) facts
  FROM (
    SELECT matched_facility_id facility_id, coalesce(issuer_publisher,evidence_class) publisher, source_url url,
      event_date event, publication_date published, date_checked checked, source_summary excerpt,
      concat_ws('. ',match_notes,buyer_vs_delivery_note,'Source summary. Confirm current service status with the facility.') rationale,
      evidence_class source_type
    FROM workspace.referral_verification.external_evidence_ext
    WHERE match_status = 'matched' AND matched_facility_id IS NOT NULL AND service = query_service
    UNION ALL
    SELECT facility_id,publisher,url,event,published,checked,excerpt,rationale,source_type
    FROM workspace.referral_verification.frontend_source_signals
    WHERE review_status = 'reviewed' AND (service IS NULL OR service = query_service)
  ) indexed GROUP BY facility_id
), packed AS (
  SELECT *, named_struct(
    'id',id,'name',name,'place',concat_ws(', ',city,state),'address',address,'virtueAddress',address,
    'km',if(loc_conflict,NULL,round(raw_km,1)),'campusCorroborated',false,
    'tier',tier,'baselineRank',if(loc_conflict,NULL,position),'rank',cast(NULL AS INT),
    'claimType',claim_type,'claimSubtype',claim_subtype,'claimConflict',claim_conflict,'locationFlags',coalesce(location_flags,array()),
    'claim',named_struct('field',claim_field,'excerpt',excerpt),
    'sourceUrls',coalesce(slice(filter(from_json(source_urls,'array<string>'), x->x IS NOT NULL),1,4),array()),
    'evidence',coalesce(slice(facts,1,8),array()),'website',website,'facebook',facebook,'phone',phone) item
  FROM sorted LEFT JOIN signals ON id=facility_id WHERE position <= 3 OR evidence_position <= 3
), grouped AS (
  SELECT transform(array_sort(collect_list(CASE WHEN NOT loc_conflict AND position <= 3 THEN
      named_struct('pos',position,'item',item) END)), x->x.item) baseline,
    transform(array_sort(collect_list(CASE WHEN tier = 0 AND evidence_position <= 3 THEN
      named_struct('pos',evidence_position,'item',item) END)), x->x.item) leads,
    transform(array_sort(collect_list(CASE WHEN tier < 0 AND evidence_position <= 1 THEN
      named_struct('pos',-tier,'item',item) END)), x->x.item) exclusions
  FROM packed
)
SELECT to_json(named_struct('location',(SELECT raw_location FROM input),'service',query_service,
  'originMethod',(SELECT method FROM origin),
  'message', CASE WHEN NOT EXISTS(SELECT 1 FROM origin) THEN
    CASE WHEN (SELECT count(DISTINCT state) FROM matches) > 1
      THEN 'This place name matches more than one state. Add the city or state, or use a PIN code.'
      ELSE 'No usable origin found. Try locality and city, city and state, a six-digit PIN, or latitude and longitude in India.' END
    ELSE '' END,
  'baseline',baseline,'supported',array(),'exclusions',exclusions,'leads',leads),map('ignoreNullFields','false')) payload
FROM grouped
