const STATUS = document.getElementById('status');
const TABLE_BODY = document.getElementById('tableBody');
const REFRESH_BTN = document.getElementById('refreshBtn');

function escapeHtml(value) {
  const div = document.createElement('div');
  div.textContent = value ?? '';
  return div.innerHTML;
}

function renderRow(trade) {
  const tr = document.createElement('tr');
  const typeClass = `trade-${trade.typeClass}`;

  tr.innerHTML = `
    <td class="font-medium">${escapeHtml(trade.filingDate)}</td>
    <td><a href="https://finance.yahoo.com/quote/${encodeURIComponent(trade.ticker)}"
           target="_blank" rel="noopener noreferrer"
           class="text-blue-600 hover:underline font-medium">${escapeHtml(trade.ticker)}</a></td>
    <td class="max-w-xs truncate" title="${escapeHtml(trade.company)}">${escapeHtml(trade.company)}</td>
    <td class="max-w-xs truncate" title="${escapeHtml(trade.insider)}">${escapeHtml(trade.insider)}</td>
    <td class="max-w-xs truncate text-gray-600" title="${escapeHtml(trade.title)}">${escapeHtml(trade.title)}</td>
    <td class="${typeClass}">${escapeHtml(trade.tradeType)}</td>
    <td>${escapeHtml(trade.price)}</td>
    <td class="font-mono">${escapeHtml(trade.qty)}</td>
    <td class="font-medium">${escapeHtml(trade.value)}</td>
  `;
  return tr;
}

async function fetchTrades() {
  REFRESH_BTN.disabled = true;
  STATUS.textContent = 'Fetching latest insider trades...';

  try {
    const response = await fetch('/api/trades');
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || `Request failed with status ${response.status}`);
    }

    TABLE_BODY.innerHTML = '';
    data.trades.forEach(trade => TABLE_BODY.appendChild(renderRow(trade)));

    const cacheNote = data.cached ? ' (cached)' : '';
    const warningNote = data.warning ? ` — showing last known data: ${data.warning}` : '';
    STATUS.textContent = `Loaded ${data.trades.length} recent trades${cacheNote}${warningNote}`;
  } catch (err) {
    console.error(err);
    STATUS.textContent = 'Failed to fetch trades. Please try again in a moment.';
  } finally {
    REFRESH_BTN.disabled = false;
  }
}

REFRESH_BTN.addEventListener('click', fetchTrades);
window.addEventListener('DOMContentLoaded', fetchTrades);
