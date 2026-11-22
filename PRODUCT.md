# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- Inferred user of the workflow: someone looking for a nearby facility in India for a specific care need. Whether to prioritize referral coordinators, patients, or caregivers in future work is open.

## Product Purpose

Atlas helps users compare nearby facilities in India using the Virtue Foundation dataset and reviewed evidence. A successful search helps the user identify leads worth following up on and understand the strength and limits of the evidence for each facility.

## Positioning

Atlas ranks by expected time to care when a service has a fitted model. Otherwise, it orders directory leads by service scope and proximity. Results show the matching claim, supporting sources, and location or service conflicts that affect the ranking.

## Operating Context

- Users enter a city, district and state, PIN, or coordinates and describe the care needed. Care descriptions should omit names and other identifying details.
- The Databricks app and live search notebook use the same Unity Catalog functions. The app can interpret free text when configured with an OpenAI key and accepts exact catalog terms without it.

## Capabilities and Constraints

- Search covers a defined service catalog and looks for facility claims within 100 km of the resolved origin. Ambiguous place names can be retried with a PIN or coordinates.
- An explicit service mention can provide a lead. Match strength, source scope, and location conflicts determine what can be claimed about the facility. Results with location conflicts have neither a rank nor a distance.

- Facility cards link to published phone numbers when available. The app surfaces a call recommendation when the fitted model estimates sufficient value.

## Evidence on Hand

- [Referral search SQL](databricks/referral_search.sql) and [service catalog](databricks/referral_service_catalog.sql) define the supported search and ranking behavior.
- The [project README](README.md) describes evidence collection, campus matching, review, and publication.

## Product Principles

- Show the evidence and conflicts behind a match.
- Keep claims specific to the campus and the documented scope of care.
