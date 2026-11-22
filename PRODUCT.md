# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- Inferred audience for the current private app and submission notebook: datathon evaluators assessing the referral workflow.
- Inferred user of the workflow: someone looking for a nearby facility in India for a specific care need. Whether to prioritize referral coordinators, patients, or caregivers in future work is open.

## Product Purpose

Find the right care helps users compare nearby facilities in India using the Virtue Foundation dataset and reviewed evidence. A successful search helps the user identify leads worth following up on and understand the strength and limits of the evidence for each facility.

## Positioning

The search ranks facility claims using service scope, proximity, and reviewed evidence tied to the facility campus. Results show the matching claim, supporting sources, and location or service conflicts that affect the ranking.

## Operating Context

- Users enter a city, district and state, PIN, or coordinates and describe the care needed. Care descriptions should omit names and other identifying details.
- The private Databricks app and submission notebook use the same Unity Catalog referral search function. The app can interpret free text when configured with an OpenAI key and accepts exact catalog terms without it.
- The Bhagalpur dialysis search opens a dated replay from February 18, 2024. Users can run a live directory search for the same inputs.

## Capabilities and Constraints

- Search covers a defined service catalog and looks for facility claims within 100 km of the resolved origin. Ambiguous place names can be retried with a PIN or coordinates.
- An explicit service mention can provide a lead. Match strength, source scope, and location conflicts determine what can be claimed about the facility. Results with location conflicts have neither a rank nor a distance.
- The Hindi dialysis phone check for Mayaganj Hospital is a demo that calls a configured team-owned number. Keypad replies are labeled as simulated staff responses. A call without a valid reply stays unconfirmed.

## Evidence on Hand

- [Referral search SQL](databricks/referral_search.sql) and [service catalog](databricks/referral_service_catalog.sql) define the supported search and ranking behavior.
- The [submission notebook](databricks/Explore%20live%20referrals.py) supports Palwal MRI and Bhagalpur dialysis scenarios.
- The [project README](README.md) describes evidence collection, campus matching, review, and publication.

## Product Principles

- Show the evidence and conflicts behind a match.
- Keep claims specific to the campus and the documented scope of care.
- Identify dated replays and simulated confirmations where users encounter them.
