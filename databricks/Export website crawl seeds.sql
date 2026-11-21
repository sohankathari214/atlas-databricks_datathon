-- Databricks notebook source
SELECT unique_id AS facility_id, name, officialWebsite AS website,
  concat_ws(', ', address_city, address_stateOrRegion) AS place,
  concat_ws(', ', address_line1, address_line2, address_city, address_stateOrRegion, address_zipOrPostcode) AS address
FROM databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities
WHERE nullif(trim(officialWebsite),'') IS NOT NULL
ORDER BY facility_id;
