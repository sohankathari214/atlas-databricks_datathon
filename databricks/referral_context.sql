CREATE OR REPLACE FUNCTION workspace.referral_verification.referral_context(submitted_at_utc STRING)
RETURNS TABLE (payload STRING)
RETURN
WITH local_clock AS (
  SELECT from_utc_timestamp(CAST(submitted_at_utc AS TIMESTAMP_NTZ), 'Asia/Kolkata') AS local_time
)
SELECT to_json(named_struct(
  'localTime', date_format(local_time, 'dd MMM yyyy, HH:mm'),
  'overnight', hour(local_time) < 8 OR hour(local_time) >= 20,
  'southwestMonsoonWindow', month(local_time) BETWEEN 6 AND 9,
  'roadStatus', 'unknown',
  'capacityStatus', 'unknown'
)) AS payload
FROM local_clock
