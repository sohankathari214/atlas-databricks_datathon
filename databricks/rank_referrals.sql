CREATE OR REPLACE FUNCTION workspace.saboot.rank_referrals(query_location STRING, query_service STRING)
RETURNS TABLE (payload STRING)
COMMENT 'Rank reviewed facility evidence by expected time to care and the value of one call.'
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
), settings AS (
  SELECT 60D * 1.3D / 30D travel_rate, 10D overhead, 30D turn_away, 240D no_care, 3D call_cost
), model AS (
  SELECT model_version, trained_services, headline FROM workspace.saboot.model_card LIMIT 1
), facility_rows AS (
  SELECT p.facility_id id, p.p, p.latitude lat, p.longitude lon, p.location_conflict,
    p.top_reasons, f.name, f.address_city city, f.address_stateOrRegion state,
    concat_ws(', ',f.address_line1,f.address_line2,f.address_city,f.address_stateOrRegion,f.address_zipOrPostcode) address,
    f.officialWebsite website,f.facebookLink facebook,f.source_urls,
    CASE WHEN trim(f.officialPhone) RLIKE r'^\+?[0-9][0-9 ()-]{7,17}[0-9]$'
      THEN regexp_replace(trim(f.officialPhone),'[^+0-9]','') END phone,
    c.best_claim_type claim_type,c.best_claim_subtype claim_subtype,
    c.best_claim_source_field claim_field,c.best_claim_excerpt excerpt,
    coalesce(c.has_conflicting_evidence,false) claim_conflict,g.location_flags,
    p.p < 0.1D AND coalesce(c.best_claim_type IN ('explicit_absence','offsite_referral','planned'),false) negative_exclusion
  FROM workspace.saboot.facility_posterior p
  JOIN databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities f ON p.facility_id=f.unique_id
  LEFT JOIN workspace.referral_verification.v_service_best_claims c ON p.facility_id=c.facility_id AND p.service=c.service
  LEFT JOIN workspace.referral_verification.facility_location_flags g ON p.facility_id=g.unique_id
  WHERE p.service=query_service
), candidate_distances AS (
  SELECT f.*, 12742D * asin(sqrt(least(1D,pow(sin(radians(f.lat-o.lat)/2),2)
    + cos(radians(o.lat))*cos(radians(f.lat))*pow(sin(radians(f.lon-o.lon)/2),2)))) km
  FROM facility_rows f CROSS JOIN origin o
  WHERE f.lat BETWEEN 6 AND 38 AND f.lon BETWEEN 68 AND 98 AND abs(f.lat-o.lat)<1.4D AND abs(f.lon-o.lon)<2D
), candidates AS (
  SELECT d.id,d.p,d.lat,d.lon,d.km,s.travel_rate*d.km+s.overhead direct_min
  FROM candidate_distances d CROSS JOIN settings s
  WHERE d.km<=100 AND NOT d.location_conflict AND NOT d.negative_exclusion
), pair_costs AS (
  SELECT a.id,b.id backup_id,
    s.travel_rate*12742D*asin(sqrt(least(1D,pow(sin(radians(a.lat-b.lat)/2),2)
      +cos(radians(a.lat))*cos(radians(b.lat))*pow(sin(radians(a.lon-b.lon)/2),2))))
      +s.overhead+(1D-b.p)*s.no_care cost
  FROM candidates a CROSS JOIN candidates b CROSS JOIN settings s WHERE a.id<>b.id
), backup_order AS (
  SELECT *,row_number() OVER(PARTITION BY id ORDER BY cost,backup_id) seq FROM pair_costs
), backups AS (
  SELECT id,max(if(seq=1,backup_id,NULL)) first_backup,
    max(if(seq=1,cost,NULL)) first_cost,max(if(seq=2,cost,NULL)) second_cost
  FROM backup_order WHERE seq<=2 GROUP BY id
), costs AS (
  SELECT c.*,b.first_backup,b.first_cost,b.second_cost,
    c.direct_min+(1D-c.p)*coalesce(s.turn_away+b.first_cost,s.no_care) etc_min
  FROM candidates c LEFT JOIN backups b USING(id) CROSS JOIN settings s
), ordered AS (
  SELECT *,row_number() OVER(ORDER BY etc_min,p DESC,km,id) etc_rank,
    row_number() OVER(ORDER BY km,id) distance_rank,min(etc_min) OVER() best_etc
  FROM costs
), without_call AS (
  SELECT a.id,min(b.direct_min+(1D-b.p)*
    coalesce(s.turn_away+if(b.first_backup=a.id,b.second_cost,b.first_cost),s.no_care)) no_min
  FROM ordered a JOIN ordered b ON a.id<>b.id CROSS JOIN settings s
  WHERE a.etc_rank<=5 GROUP BY a.id
), call_gain AS (
  SELECT a.id,greatest(0D,a.best_etc-(a.p*a.direct_min+(1D-a.p)*coalesce(w.no_min,s.no_care))) voi
  FROM ordered a LEFT JOIN without_call w USING(id) CROSS JOIN settings s WHERE a.etc_rank<=5
), call_pick AS (
  SELECT g.id FROM call_gain g JOIN ordered a USING(id) CROSS JOIN settings s
  WHERE g.voi>s.call_cost ORDER BY g.voi DESC,a.etc_rank LIMIT 1
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
  SELECT named_struct(
    'id',d.id,'name',d.name,'place',concat_ws(', ',d.city,d.state),'address',d.address,'virtueAddress',d.address,
    'km',if(d.location_conflict,NULL,round(d.km,1)), 'campusCorroborated',false,
    'tier',if(d.location_conflict,-3,if(d.negative_exclusion,-1,0)),
    'baselineRank',o.distance_rank,'rank',o.etc_rank,'p',d.p,'etcMin',round(o.etc_min,1),'voiMin',round(g.voi,1),
    'topReasons',d.top_reasons,'claimType',d.claim_type,'claimSubtype',d.claim_subtype,'claimConflict',d.claim_conflict,
    'locationFlags',coalesce(d.location_flags,array()),'phone',d.phone,
    'claim',if(d.excerpt IS NULL,NULL,named_struct('field',d.claim_field,'excerpt',d.excerpt)),
    'sourceUrls',coalesce(slice(filter(from_json(d.source_urls,'array<string>'),x->x IS NOT NULL),1,4),array()),
    'evidence',coalesce(slice(array_sort(si.facts),1,8),array()),'website',d.website,'facebook',d.facebook) item,
    o.etc_rank,o.distance_rank,d.p,d.location_conflict OR d.negative_exclusion excluded,d.km
  FROM candidate_distances d
  LEFT JOIN ordered o USING(id) LEFT JOIN call_gain g USING(id) LEFT JOIN signals si ON d.id=si.facility_id
  WHERE d.km<=100 AND (o.etc_rank IS NOT NULL OR d.location_conflict OR d.negative_exclusion)
), grouped AS (
  SELECT transform(array_sort(collect_list(if(distance_rank<=3,named_struct('pos',distance_rank,'item',item),NULL))),x->x.item) baseline,
    transform(array_sort(collect_list(if(etc_rank<=10 AND p>=0.5D,named_struct('pos',etc_rank,'item',item),NULL))),x->x.item) supported,
    transform(array_sort(collect_list(if(etc_rank<=10 AND p<0.5D,named_struct('pos',etc_rank,'item',item),NULL))),x->x.item) leads,
    transform(slice(array_sort(collect_list(if(excluded,named_struct('km',km,'item',item),NULL))),1,5),x->x.item) exclusions, min(item.etcMin) etc_best
  FROM packed
)
SELECT to_json(named_struct(
  'location',(SELECT raw_location FROM input),'service',query_service,'originMethod',(SELECT method FROM origin),
  'rankingAvailable',coalesce(array_contains(from_json(model.trained_services,'array<string>'),query_service),false),
  'message',CASE WHEN NOT EXISTS(SELECT 1 FROM origin) THEN
    CASE WHEN (SELECT count(DISTINCT state) FROM matches)>1 THEN 'This place name matches more than one state. Add the city or state, or use a PIN code.'
    ELSE 'No usable origin found. Enter a locality and state, a six-digit PIN, or coordinates in India.' END
    WHEN size(supported)+size(leads)=0 THEN 'No eligible modelled facilities found within 100 km.' ELSE '' END,
  'callFirst',call_pick.id,'etcBest',etc_best,
  'evaluation',try_element_at(filter(from_json(model.headline,
    'array<struct<service:string,n_searches:int,minutes_saved:double,ci_low:double,ci_high:double,p_value:double>>'),
    h->h.service=query_service),1),
  'baseline',baseline,'supported',supported,'exclusions',exclusions,'leads',leads), map('ignoreNullFields','false')) payload
FROM grouped LEFT JOIN model ON true LEFT JOIN call_pick ON true
