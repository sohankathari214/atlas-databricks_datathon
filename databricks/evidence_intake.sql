CREATE TABLE IF NOT EXISTS workspace.referral_verification.frontend_source_signals (
  signal_id STRING NOT NULL,
  facility_id STRING NOT NULL,
  service STRING,
  source_type STRING NOT NULL,
  publisher STRING NOT NULL,
  url STRING NOT NULL,
  checked DATE,
  event DATE,
  published DATE,
  excerpt STRING,
  rationale STRING,
  review_status STRING NOT NULL
) USING DELTA
COMMENT 'Reviewed campus cross-checks and source leads. These signals do not establish current availability.'
