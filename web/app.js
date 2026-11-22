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

function card(row, data, mode) {
  const distance = row.km === null ? 'Distance withheld' : `${row.km.toFixed(1)} km straight-line`;
  const query = encodeURIComponent(row.name + ', ' + row.address);
  const maps = row.tier === -3 ? '' : link('Google Maps', 'https://www.google.com/maps/search/?api=1&query=' + query) + ' ' +
    link('OpenStreetMap', 'https://www.openstreetmap.org/search?query=' + query);
  const website = row.website && /^https?:\/\//i.test(row.website) ? row.website : row.website && 'https://' + row.website;
  const otherLinks = [link('Hospital website',website), link('Facebook',row.facebook),
    link('News, tenders and jobs','https://search.brave.com/search?q=' + encodeURIComponent(row.name+' '+row.place+' '+serviceLabels[data.service]+' news OR tender OR jobs'))].filter(Boolean).join(' ');
  const phoneCheck = data.service === 'dialysis' && row.id === '29903d8a-3433-4240-b1eb-91094a7551d4';
  return `<article class="card ${mode}">
    <div class="facility-copy">
    <h3><span translate="no">${escape(row.name)}</span></h3>
    <p class="metadata"><span translate="no">${escape(row.place)}</span> · ${distance}</p>
    <div class="phone-check">
      <button type="button" data-phone-check${phoneCheck ? ' data-dialysis-enabled' : ''}>Confirm by phone</button>
      <p class="phone-status" role="status"></p>
    </div>
    ${evidence(row, data.cutoff, [maps, otherLinks].filter(Boolean).join(' '))}
  </article>`;
}

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
          ${listings.map(row => card(row, data, 'baseline')).join('')}</details>`
      : '<p class="state" role="status">No usable emergency department listings near this location.</p>';
    return;
  }
  const service = serviceLabels[data.service];
  const timing = data.cutoff ? `Historical replay · ${date(data.cutoff)}` : '';
  const [mainExclusion, ...otherExclusions] = data.exclusions;
  const [topLead, ...otherLeads] = data.leads;
  const more = [...otherExclusions.map(row => card(row, data, 'excluded')),
    ...(data.supported.length ? data.leads : otherLeads).map(row => card(row, data, 'lead'))];
  results.innerHTML = `<div class="results-head"><h2><span translate="no">${escape(data.location)}</span> · ${service}</h2>${timing ? `<p role="status">${timing}</p>` : ''}</div>
    ${data.cutoff ? `<div class="panel replay-note"><p><b>Reviewed historical example.</b> The evidence shows what was reported by ${escape(date(data.cutoff))}. Current service availability is unknown.</p>
      <button type="button" id="live-results">Run live directory search</button></div>` : ''}
      <section class="panel aware" aria-label="Evidence-aware results"><h2 class="section-label">Evidence-aware results</h2><p class="sub">Current service availability and slots unknown</p>
        ${data.supported.map(row => card(row, data, 'supported')).join('')}
        ${!data.supported.length && topLead ? card(topLead, data, 'lead') : ''}
        ${mainExclusion ? card(mainExclusion, data, 'excluded') : ''}
        ${more.length ? `<details class="more"><summary>Other candidates (${more.length})</summary>${more.join('')}</details>` : ''}
      </section>`;
  results.querySelector('#live-results')?.addEventListener('click', () => search({ useReplay: false }));
}

const phoneMessages = {
  yes: 'Simulated staff response: Yes, accepting dialysis referrals today.',
  no: 'Simulated staff response: No, not accepting dialysis referrals today.',
  unconfirmed: 'Unconfirmed: No valid keypad response.',
  setup_required: 'Phone verification needs the Twilio credentials and verified team number.',
  busy: 'A phone check is already in progress.',
  limit: 'The phone-check limit for this app session has been reached.',
  provider_error: 'Unconfirmed: Twilio could not complete the phone check.',
  not_found: 'Unconfirmed: The call status is no longer available.',
};

async function confirmByPhone(event) {
  const button = event.target.closest('[data-phone-check]');
  if (!button) return;
  const status = button.closest('.phone-check').querySelector('.phone-status');
  if (!button.hasAttribute('data-dialysis-enabled')) {
    status.textContent = 'Phone confirmation is available for the Mayaganj Hospital dialysis result in Bhagalpur.';
    return;
  }
  button.disabled = true;
  status.textContent = 'Calling the team phone…';
  try {
    const response = await fetch('/api/dialysis-phone-check', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ facilityId: '29903d8a-3433-4240-b1eb-91094a7551d4' }),
    });
    let update = await response.json();
    const id = update.id;
    while (update.status === 'pending' && button.isConnected) {
      await new Promise(resolve => setTimeout(resolve, 2200));
      if (!button.isConnected) return;
      const check = await fetch('/api/dialysis-phone-check?' + new URLSearchParams({ id }));
      update = await check.json();
    }
    status.textContent = phoneMessages[update.status] ?? phoneMessages.provider_error;
  } catch {
    status.textContent = phoneMessages.provider_error;
  } finally {
    button.disabled = false;
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
