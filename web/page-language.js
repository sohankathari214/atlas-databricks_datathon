const selector = document.querySelector('#language');
const status = document.querySelector('#language-status');
const original = new WeakMap();
const dictionaries = new Map();
const translatableAttributes = ['placeholder', 'aria-label'];
const encoder = new TextEncoder();
let scheduled = false;
let active;
let language = 'en';

function entries() {
  const items = [];
  function collect(node, key, read, write) {
    const current = read();
    if (!current?.trim() || !/\p{L}/u.test(current)) return;
    if (!original.has(node)) original.set(node, {});
    const records = original.get(node);
    if (records[key]?.rendered !== current) records[key] = { source: current, rendered: current };
    const record = records[key];
    items.push({
      source: record.source.trim(),
      apply(value) {
        if (!node.isConnected || read() !== record.rendered) return;
        record.rendered = record.source.replace(/\S[\s\S]*\S|\S/, () => value);
        if (record.rendered !== read()) write(record.rendered);
      },
    });
  }
  const walker = document.createTreeWalker(document.documentElement, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node.parentElement.closest('script, style, [translate="no"]')) continue;
    collect(node, 'text', () => node.data, value => { node.data = value; });
  }
  for (const element of document.querySelectorAll('[placeholder], [aria-label]')) {
    if (element.closest('[translate="no"]')) continue;
    for (const name of translatableAttributes) {
      collect(element, name, () => element.getAttribute(name), value => element.setAttribute(name, value));
    }
  }
  return items;
}

async function update() {
  if (active) return;
  const nodes = entries();
  if (language === 'en') {
    nodes.forEach(node => node.apply(node.source));
    return;
  }
  const target = language;
  if (!dictionaries.has(target)) dictionaries.set(target, new Map());
  const dictionary = dictionaries.get(target);
  const missing = new Set();
  for (const node of nodes) {
    if (dictionary.has(node.source)) node.apply(dictionary.get(node.source));
    else node.apply(node.source);
    if (!dictionary.has(node.source) && encoder.encode(JSON.stringify([node.source])).length <= 3900) missing.add(node.source);
  }
  if (!missing.size) return;
  const controller = new AbortController();
  active = controller;
  status.textContent = 'Translating…';
  function batches() {
    const groups = [[]];
    for (const value of missing) {
      let group = groups.at(-1);
      if (group.length >= 30 || encoder.encode(JSON.stringify([...group, value])).length > 3900) {
        if (group.length) groups.push(group = []);
      }
      group.push(value);
    }
    return groups.filter(group => group.length);
  }
  try {
    for (const strings of batches()) {
      const response = await fetch('/api/page-translation', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        signal: controller.signal, body: JSON.stringify({ language: target, strings }),
      });
      if (!response.ok) throw new Error('Translation failed');
      const data = await response.json();
      strings.forEach((source, index) => dictionary.set(source, data.strings[index]));
    }
    if (controller.signal.aborted) return;
    // Apply to the current DOM, including any results added during translation.
    for (const node of entries()) if (dictionary.has(node.source)) node.apply(dictionary.get(node.source));
    status.textContent = '';
    schedule();
  } catch {
    if (!controller.signal.aborted) status.textContent = 'Translation unavailable. English is shown for untranslated text.';
  } finally {
    if (active === controller) active = undefined;
  }
}

function schedule() {
  if (scheduled) return;
  scheduled = true;
  requestAnimationFrame(() => {
    scheduled = false;
    update();
  });
}

function selectLanguage(value) {
  active?.abort();
  active = undefined;
  language = value;
  document.documentElement.lang = value;
  status.textContent = '';
  schedule();
}

const observer = new MutationObserver(records => {
  if (records.some(record => {
    const element = record.target.nodeType === Node.TEXT_NODE ? record.target.parentElement : record.target;
    if (element?.closest('[translate="no"]')) return false;
    const key = record.type === 'characterData' ? 'text' : record.attributeName;
    return record.type === 'childList' || original.get(record.target)?.[key]?.rendered
      !== (key === 'text' ? record.target.data : element?.getAttribute(key));
  })) schedule();
});
observer.observe(document.documentElement, {
  subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: translatableAttributes,
});

selector.addEventListener('change', () => {
  try { localStorage.setItem('referral-language', selector.value); } catch {}
  selectLanguage(selector.value);
});
try {
  const saved = localStorage.getItem('referral-language');
  if ([...selector.options].some(option => option.value === saved)) selector.value = saved;
} catch {}
if (selector.value !== 'en') selectLanguage(selector.value);
