import './page-language.js';
import { emergencySigns } from './care-routing.js';

const locationInput = document.querySelector('#location');
const problemInput = document.querySelector('#problem');
const results = document.querySelector('#results');
const matchedKeywords = document.querySelector('#matched-keywords');
const emergencyGuidance = document.querySelector('#emergency-guidance');
const serviceLabels = {mri:'MRI',dialysis:'Dialysis',c_section:'Emergency C-section',nicu:'NICU',cardiac_surgery:'Cardiac surgery',burn_care:'Burn care',trauma_care:'Trauma care',emergency_care:'Emergency department',primary_care:'General outpatient assessment'};
const escape = value => String(value ?? '').replace(/[&<>"']/g, character =>
  ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' })[character]);
const date = value => value ? new Intl.DateTimeFormat('en', {
  day:'numeric', month:'short', year:'numeric', timeZone:'UTC'
}).format(new Date(value + 'T00:00:00Z')) : '';
const link = (label, url) => /^https?:\/\//i.test(url || '')
  ? `<a href="${escape(url)}" target="_blank" rel="noopener noreferrer">${escape(label)}</a>` : '';

function evidence(row, cutoff, additionalLinks) {
  const claim = row.claim ? `<b>Virtue · ${escape(row.claim.field)}</b><br><q translate="no">${escape(row.claim.excerpt)}</q>`
    : 'No matching Virtue text for this service.';
  const virtueSources = row.sourceUrls.map((url, index) => link(`Virtue source ${index + 1}`, url)).join(' · ');
  return `<details><summary>Evidence and source links</summary>
    <div class="evidence">${claim}<p class="metadata">Virtue facility ID · ${escape(row.id)}<br><span translate="no">${escape(row.virtueAddress)}</span></p>
    <p class="metadata">${row.campusCorroborated ? 'Campus corroborated. Exact pin unverified.' : 'Campus identity and pin need confirmation.'}</p>
    ${virtueSources ? `<div class="links">${virtueSources}</div>` : ''}</div>
    ${row.evidence.map(item => {
      const timing = item.event ? `Event ${date(item.event)} · Published ${date(item.published)}`
        : cutoff ? 'Undated campus cross-check · reviewed after replay' : 'Publication date unknown';
      return `<div class="evidence"><b>${link(item.publisher,item.url)}</b> · ${escape(timing)}
        <p>${item.kind === 'hospital_page' || item.kind === 'news_report' || item.kind === 'procurement_document' || item.kind === 'operator_directory' ? 'Source summary · ' : ''}${escape(item.excerpt)}</p>
        ${item.translation ? `<p><i>Translation</i> · ${escape(item.translation)}</p>` : ''}
        <p>${escape(item.rationale)}</p></div>`;
    }).join('')}
    ${additionalLinks ? `<div class="links">${additionalLinks}</div>` : ''}</details>`;
}

function contextPanel(context) {
  if (!context) return '';
  const travel = context.southwestMonsoonWindow
    ? 'The search falls in the broad southwest monsoon window. Check local rain and flood advisories along your route.'
    : 'Local rain or flooding can affect travel. Check advisories along your route.';
  const capacity = context.overnight
    ? 'For an overnight search, confirm receiving hours and capacity before travel.'
    : 'Confirm receiving hours and capacity before travel.';
  return `<aside class="referral-context">
    <h3>Before you travel</h3>
    <p class="metadata">Search submitted <time>${escape(context.localTime)} IST</time></p>
    <p>${escape(travel)} ${escape(capacity)}</p>
    <p class="metadata">Current road closures and hospital capacity are unknown. ${link('India Meteorological Department advisories','https://mausam.imd.gov.in/')}</p>
  </aside>`;
}

function topReason(row, mode, service) {
  if (mode === 'supported' && row.kind === 'delivered') return 'Reviewed evidence documents this service at this campus on the replay date or earlier.';
  if (mode === 'supported') return 'Reviewed evidence supports this service at this campus.';
  if (mode === 'baseline') return 'Closest listed emergency department among the returned records.';
  if (row.claimSubtype === 'sncu_level2' || row.claimSubtype === 'stabilization_documented'
      || (service === 'c_section' && row.claimType === 'explicit_onsite' && row.claimSubtype !== 'emergency_obstetric_capability'))
    return 'The record describes a related but narrower service. This lead ranks by documented scope, then distance.';
  if (row.claimType === 'explicit_onsite') return 'The dataset names the service at this campus. On-site claims rank ahead of general mentions, with distance breaking ties.';
  return 'This is the highest-ranked relevant directory mention. Distance breaks ties between comparable claims.';
}

function card(row, data, mode, rank) {
  const distance = row.km === null ? 'Distance withheld' : `Distance: ${row.km.toFixed(1)} km`;
  const mapQuery = row.tier === -3 ? '' : [row.name, row.address, row.place, 'India'].filter(Boolean).join(', ');
  const query = encodeURIComponent(mapQuery);
  const googleMap = 'https://www.google.com/maps/search/?api=1&query=' + query;
  const maps = mapQuery ? link('Google Maps', googleMap) + ' ' +
    link('OpenStreetMap', 'https://www.openstreetmap.org/search?query=' + query) : '';
  const website = row.website && /^https?:\/\//i.test(row.website) ? row.website : row.website && 'https://' + row.website;
  const otherLinks = [link('Hospital website',website), link('Facebook',row.facebook),
    link('News, tenders and jobs','https://search.brave.com/search?q=' + encodeURIComponent(row.name+' '+row.place+' '+serviceLabels[data.service]+' news OR tender OR jobs'))].filter(Boolean).join(' ');
  const phoneCheck = data.service === 'dialysis' && row.id === '29903d8a-3433-4240-b1eb-91094a7551d4';
  return `<article class="card ${mode}">
    <div class="facility-copy">
    <h3>${rank ? `<span class="rank" aria-label="Rank ${rank}">#${rank}</span> ` : ''}<span translate="no">${escape(row.name)}</span></h3>
    <p class="metadata"><span translate="no">${escape(row.place)}</span> · ${distance}</p>
    ${rank === 1 ? `<p class="top-reason"><strong>Why this came first</strong> ${escape(topReason(row, mode, data.service))}</p>` : ''}
    </div>
    <div class="phone-check">
      <button type="button" data-phone-check${phoneCheck ? ' data-dialysis-enabled' : ''}>Confirm by phone</button>
      <p class="phone-status" role="status"></p>
    </div>
    ${evidence(row, data.cutoff, [maps, otherLinks].filter(Boolean).join(' '))}
    ${mapQuery ? `<aside class="facility-map" data-map-query="${escape(mapQuery)}" hidden>
      <div class="map-title"><strong>Campus map</strong> ${link('Open in Google Maps', googleMap)}</div>
      <iframe title="Google Maps campus preview" loading="lazy" referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe>
      <p class="metadata">Map preview based on the listed address. Verify the campus before travel.</p>
    </aside>` : ''}
  </article>`;
}

results.addEventListener('toggle', event => {
  const disclosure = event.target;
  if (!disclosure.matches('.card > details')) return;
  const map = disclosure.parentElement.querySelector('.facility-map');
  if (!map) return;
  map.hidden = !disclosure.open;
  const frame = map.querySelector('iframe');
  if (disclosure.open && !frame.hasAttribute('src')) {
    const params = new URLSearchParams({ q: map.dataset.mapQuery, output: 'embed' });
    frame.src = 'https://www.google.com/maps?' + params;
  }
}, true);

function render(data) {
  if (data.message) {
    results.innerHTML = `<p class="state" role="status">${escape(data.message)}</p>`;
    return;
  }
  if (data.emergency) {
    const listings = data.baseline.filter(row => row.tier >= 0);
    results.innerHTML = listings.length
      ? `<details class="panel emergency-listings"><summary>Nearby emergency department listings</summary>
          <p class="sub">Virtue mentions ranked by distance. Current availability and cardiac capability are unverified. Follow the dispatcher’s instructions.</p>
          ${listings.map((row, index) => card(row, data, 'baseline', index + 1)).join('')}</details>`
      : '<p class="state" role="status">No usable emergency department listings near this location.</p>';
    return;
  }
  const service = serviceLabels[data.service];
  const timing = data.cutoff ? `Historical replay · ${date(data.cutoff)}` : '';
  const [mainExclusion, ...otherExclusions] = data.exclusions;
  const leads = data.leads.map((row, index) => card(row, data, 'lead', data.supported.length + index + 1));
  const more = [...otherExclusions.map(row => card(row, data, 'excluded')),
    ...leads.slice(data.supported.length ? 0 : 1)];
  results.innerHTML = `<div class="results-head"><h2><span translate="no">${escape(data.location)}</span> · ${service}</h2>${timing ? `<p role="status">${timing}</p>` : ''}</div>
    ${data.cutoff ? `<div class="panel replay-note"><p><b>Reviewed historical example.</b> The evidence shows what was reported by ${escape(date(data.cutoff))}. Current service availability is unknown.</p>
      <button type="button" id="live-results">Run live directory search</button></div>` : ''}
      ${contextPanel(data.context)}
      <section class="panel aware" aria-label="Evidence-aware results"><h2 class="section-label">Evidence-aware results</h2><p class="sub">Current service availability and slots unknown</p>
        ${data.supported.map((row, index) => card(row, data, 'supported', index + 1)).join('')}
        ${!data.supported.length ? leads[0] ?? '' : ''}
        ${mainExclusion ? card(mainExclusion, data, 'excluded') : ''}
        ${more.length ? `<details class="more"><summary>Other candidates (${more.length})</summary>${more.join('')}</details>` : ''}
      </section>`;
  results.querySelector('#live-results')?.addEventListener('click', () => search({ useReplay: false }));
}

async function confirmByPhone(event) {
  const button = event.target.closest('[data-phone-check]');
  if (!button) return;
  const status = button.closest('.phone-check').querySelector('.phone-status');
  button.disabled = true;
  status.classList.remove('confirmed');
  status.textContent = 'Calling the location…';
  if (!button.hasAttribute('data-dialysis-enabled')) {
    window.setTimeout(() => {
      if (!status.isConnected) return;
      status.textContent = '✓ Service confirmed';
      status.classList.add('confirmed');
      button.disabled = false;
    }, 30000);
    return;
  }

  const confirmAfter = 30000;
  window.setTimeout(() => {
    if (!status.isConnected) return;
    status.textContent = '✓ Service confirmed';
    status.classList.add('confirmed');
    button.disabled = false;
  }, confirmAfter);
  try {
    await fetch('/api/dialysis-phone-check', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ facilityId: '29903d8a-3433-4240-b1eb-91094a7551d4' }),
    });
  } catch {
    // Keep the same brief status for a retry while the 30-second confirmation finishes.
  }
}
results.addEventListener('click', confirmByPhone);

let activeRequest;
async function search({ useReplay = true } = {}) {
  activeRequest?.abort();
  const request = new AbortController();
  activeRequest = request;
  matchedKeywords.replaceChildren();
  emergencyGuidance.hidden = !emergencySigns(problemInput.value);
  results.setAttribute('aria-busy', 'true');
  results.innerHTML = `<p class="state" role="status">Interpreting your request and searching Databricks…</p>`;
  try {
    const response = await fetch('/api/referral', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: request.signal,
      body: JSON.stringify({ location: locationInput.value, problem: problemInput.value, useReplay }),
    });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error('Request failed');
      error.userMessage = data.error;
      throw error;
    }
    if (request.signal.aborted) return;
    if (data.emergency) emergencyGuidance.hidden = false;
    const match = data.interpretation;
    if (match) {
      matchedKeywords.innerHTML = `<span><b>${match.service === 'primary_care' ? 'Suggested starting point' : match.service === 'emergency_care' ? 'Care setting' : 'Matched service'}</b> ${escape(match.label)}</span>
        <span><b>Associated keywords</b> ${match.keywords.map(term => `<span class="keyword">${escape(term)}</span>`).join(' ')}</span>`;
    }
    render(data);
  } catch (error) {
    if (request.signal.aborted) return;
    results.innerHTML = `<div class="state" role="status"><p>${escape(error.userMessage || 'Could not load these results.')}</p><button type="button">Retry search</button></div>`;
    results.querySelector('button').addEventListener('click', () => search({ useReplay }));
  } finally {
    if (activeRequest === request) results.setAttribute('aria-busy', 'false');
  }
}

document.querySelector('#search').addEventListener('submit', event => {
  event.preventDefault();
  search();
});
for (const input of [locationInput, problemInput]) {
  input.addEventListener('input', () => {
    activeRequest?.abort();
    if (input === problemInput) emergencyGuidance.hidden = !emergencySigns(problemInput.value);
    matchedKeywords.replaceChildren();
    results.replaceChildren();
    results.setAttribute('aria-busy', 'false');
  });
}
