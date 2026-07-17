const STATUS = document.getElementById('status');
const TABLE_BODY = document.getElementById('tableBody');
const REFRESH_BTN = document.getElementById('refreshBtn');
const SOURCE_FILTER = document.getElementById('sourceFilter');
const DIR_FILTER = document.getElementById('dirFilter');

let allTrades = [];
let lastMeta = {};
const filters = { source: 'all', dir: 'all' };

function escapeHtml(value) {
  const div = document.createElement('div');
  div.textContent = value ?? '';
  return div.innerHTML;
}

function sourceBadge(trade) {
  if (trade.source === 'congress') {
    return '<span class="badge badge-congress">\u{1F3DB}\u{FE0F} Congress</span>';
  }
  return '<span class="badge badge-insider">\u{1F3E2} Insider</span>';
}

function cell(value) {
  const text = (value === undefined || value === null || value === '') ? '—' : value;
  return escapeHtml(text);
}

function renderRow(trade) {
  const tr = document.createElement('tr');
  const typeClass = `trade-${trade.typeClass}`;

  tr.innerHTML = `
    <td>${sourceBadge(trade)}</td>
    <td class="whitespace-nowrap font-medium">${cell(trade.date)}</td>
    <td><a href="https://finance.yahoo.com/quote/${encodeURIComponent(trade.ticker)}"
           target="_blank" rel="noopener noreferrer"
           class="text-blue-600 hover:underline font-medium">${cell(trade.ticker)}</a></td>
    <td class="max-w-xs truncate" title="${escapeHtml(trade.company)}">${cell(trade.company)}</td>
    <td class="max-w-xs truncate" title="${escapeHtml(trade.person)}">${cell(trade.person)}</td>
    <td class="max-w-xs truncate text-gray-600" title="${escapeHtml(trade.role)}">${cell(trade.role)}</td>
    <td class="${typeClass} whitespace-nowrap">${cell(trade.tradeType)}</td>
    <td class="font-mono text-right">${cell(trade.qty)}</td>
    <td class="text-right">${cell(trade.price)}</td>
    <td class="font-medium whitespace-nowrap text-right">${cell(trade.value)}</td>
  `;
  return tr;
}

function applyFilters() {
  return allTrades.filter(t => {
    if (filters.source !== 'all' && t.source !== filters.source) return false;
    if (filters.dir !== 'all' && t.typeClass !== filters.dir) return false;
    return true;
  });
}

function render() {
  const visible = applyFilters();
  TABLE_BODY.innerHTML = '';
  visible.forEach(trade => TABLE_BODY.appendChild(renderRow(trade)));

  const insiderN = allTrades.filter(t => t.source === 'insider').length;
  const congressN = allTrades.filter(t => t.source === 'congress').length;
  let msg = `Showing ${visible.length} of ${allTrades.length} trades ` +
            `(\u{1F3E2} ${insiderN} insider, \u{1F3DB}\u{FE0F} ${congressN} congress)`;
  if (lastMeta && lastMeta.congressEnabled === false) {
    msg += ` — congressional feed off: ${lastMeta.congressWarning || 'not configured'}`;
  } else if (lastMeta && lastMeta.congressAsOf) {
    const asOf = new Date(lastMeta.congressAsOf);
    if (!isNaN(asOf)) msg += ` — congressional data as of ${asOf.toLocaleDateString()}`;
  }
  STATUS.textContent = msg;
}

function wireFilterGroup(container, key) {
  container.addEventListener('click', (event) => {
    const btn = event.target.closest('button');
    if (!btn) return;
    filters[key] = key === 'source' ? btn.dataset.source : btn.dataset.dir;
    container.querySelectorAll('button').forEach(b => b.classList.toggle('active', b === btn));
    render();
  });
}

async function fetchTrades() {
  REFRESH_BTN.disabled = true;
  STATUS.textContent = 'Fetching latest insider and congressional trades…';

  try {
    const response = await fetch('/api/trades');
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || `Request failed with status ${response.status}`);
    }

    allTrades = Array.isArray(data.trades) ? data.trades : [];
    lastMeta = data.meta || {};
    render();
  } catch (err) {
    console.error(err);
    STATUS.textContent = 'Failed to fetch trades. Please try again in a moment.';
  } finally {
    REFRESH_BTN.disabled = false;
  }
}

wireFilterGroup(SOURCE_FILTER, 'source');
wireFilterGroup(DIR_FILTER, 'dir');
REFRESH_BTN.addEventListener('click', fetchTrades);
window.addEventListener('DOMContentLoaded', fetchTrades);
