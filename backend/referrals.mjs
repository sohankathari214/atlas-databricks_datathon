import { queryJson } from './databricks.mjs';

export function readScenario(scenario) {
  return queryJson('SELECT payload FROM workspace.referral_verification.frontend_scenarios WHERE scenario = :scenario', { scenario });
}

export function searchReferral(location, service) {
  return queryJson('SELECT payload FROM workspace.referral_verification.search_referrals(:location, :service)', { location, service });
}

export function referralContext(submittedAt) {
  return queryJson('SELECT payload FROM workspace.referral_verification.referral_context(:submittedAt)', {
    submittedAt: submittedAt.toISOString().slice(0, -1),
  });
}

let catalogCache;
let catalogExpires = 0;
export async function serviceCatalog() {
  if (catalogCache && catalogExpires > Date.now()) return catalogCache;
  const catalog = await queryJson(
    'SELECT payload FROM workspace.referral_verification.referral_service_catalog()', {},
  );
  if (!catalog.length) throw new Error('Databricks service catalog is empty');
  catalogCache = catalog;
  catalogExpires = Date.now() + 300000;
  return catalog;
}
