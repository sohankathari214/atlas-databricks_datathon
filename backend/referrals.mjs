import { queryJson } from './databricks.mjs';

export function readScenario(scenario) {
  return queryJson('SELECT payload FROM workspace.referral_verification.frontend_scenarios WHERE scenario = :scenario', { scenario });
}

export async function searchReferral(location, service) {
  const parameters = { location, service };
  const directory = () => queryJson('SELECT payload FROM workspace.referral_verification.search_referrals(:location, :service)', parameters);
  if (service === 'emergency_care' || service === 'primary_care') return directory();
  const ranked = await queryJson('SELECT payload FROM workspace.saboot.rank_referrals(:location, :service)', parameters);
  if (ranked.rankingAvailable) return ranked;
  return { ...await directory(), rankingAvailable: false };
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
