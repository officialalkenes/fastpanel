/**
 * FastPanel Standalone Debugger — client-side JS
 *
 * Manages the two-pane request inspector UI at /__fastpanel/.
 *
 * Responsibilities:
 *  1. Poll /__fastpanel/api/requests for the list of recent API calls
 *  2. Render the request list sidebar
 *  3. On request selection, fetch full panel data and render all tabs
 *  4. Handle tab switching within the selected request
 *  5. Auto-refresh the request list every 3 seconds (toggleable)
 */

(function () {
  'use strict';

  const MOUNT = window.__FP_MOUNT_PATH__ || '/__fastpanel';
  const API   = `${MOUNT}/api`;

  const SQL_KEYWORDS = /\b(SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|CROSS|ON|AND|OR|NOT|IN|IS|NULL|INSERT|INTO|VALUES|UPDATE|SET|DELETE|CREATE|DROP|ALTER|TABLE|INDEX|ORDER|BY|GROUP|HAVING|LIMIT|OFFSET|DISTINCT|AS|UNION|ALL|EXISTS|BETWEEN|LIKE|CASE|WHEN|THEN|ELSE|END|WITH|RETURNING|BEGIN|COMMIT|ROLLBACK|SAVEPOINT)\b/g;

  // ─── DOM refs ──────────────────────────────────────────────────────────────
  const requestList       = document.getElementById('fp-request-list');
  const requestCount      = document.getElementById('fp-request-count');
  const mainTabs          = document.getElementById('fp-main-tabs');
  const mainContent       = document.getElementById('fp-main-content');
  const refreshBtn        = document.getElementById('fp-refresh-btn');
  const autoRefreshCheck  = document.getElementById('fp-auto-refresh-check');

  // ─── State ────────────────────────────────────────────────────────────────
  let requests      = [];          // latest summaries from /api/requests
  let selectedId    = null;        // currently selected request_id
  let panelData     = null;        // full panel data for selected request
  let activeTab     = null;        // currently active panel tab id
  let refreshTimer  = null;

  // ─── Bootstrap ────────────────────────────────────────────────────────────
  refreshBtn.addEventListener('click', () => fetchRequests());
  autoRefreshCheck.addEventListener('change', () => {
    if (autoRefreshCheck.checked) scheduleRefresh();
    else clearTimeout(refreshTimer);
  });

  fetchRequests();
  scheduleRefresh();

  // ─── Polling ──────────────────────────────────────────────────────────────
  function scheduleRefresh() {
    clearTimeout(refreshTimer);
    if (!autoRefreshCheck.checked) return;
    refreshTimer = setTimeout(async () => {
      await fetchRequests();
      scheduleRefresh();
    }, 3000);
  }

  // ─── Fetch request list ───────────────────────────────────────────────────
  async function fetchRequests() {
    try {
      const resp = await fetch(`${API}/requests`, { headers: { Accept: 'application/json' } });
      if (!resp.ok) {
        showSidebarError(`API error ${resp.status}`);
        return;
      }
      const data = await resp.json();
      requests = data.requests || [];
      renderRequestList();

      // If the selected request is still in the list, keep it selected.
      // If it disappeared (evicted), deselect.
      if (selectedId && !requests.find(r => r.request_id === selectedId)) {
        selectedId = null;
        panelData = null;
        showPlaceholder();
      }
    } catch (err) {
      showSidebarError(`Fetch failed: ${err.message}`);
    }
  }

  // ─── Render request list ──────────────────────────────────────────────────
  function renderRequestList() {
    requestCount.textContent = requests.length;

    if (requests.length === 0) {
      requestList.innerHTML = `
        <div class="fp-placeholder" style="padding-top:40px">
          <span class="fp-placeholder-icon">🔍</span>
          <p>No requests captured yet.</p>
          <small>Make API calls to your app to see them here.</small>
        </div>`;
      return;
    }

    requestList.innerHTML = requests.map(r => {
      const activeClass = r.request_id === selectedId ? ' fp-req-active' : '';
      const methodClass = methodCssClass(r.method);
      const statusClass = statusCssClass(r.status_code);
      return `
        <div class="fp-req-row${activeClass}" data-id="${escAttr(r.request_id)}">
          <span class="fp-req-method ${methodClass}">${escHtml(r.method)}</span>
          <span class="fp-req-path" title="${escAttr(r.path)}">${escHtml(r.path)}</span>
          <span class="fp-req-status ${statusClass}">${escHtml(String(r.status_code || '—'))}</span>
          <span class="fp-req-ms">${r.total_ms}ms</span>
        </div>`;
    }).join('');

    requestList.querySelectorAll('.fp-req-row').forEach(row => {
      row.addEventListener('click', () => selectRequest(row.dataset.id));
    });
  }

  function showSidebarError(msg) {
    requestList.innerHTML = `<div class="fp-placeholder" style="padding-top:40px;color:#ff4757">${escHtml(msg)}</div>`;
  }

  // ─── Select a request ─────────────────────────────────────────────────────
  async function selectRequest(requestId) {
    if (selectedId === requestId) return;

    selectedId = requestId;
    activeTab = null;
    panelData = null;

    // Highlight selected row immediately.
    renderRequestList();

    // Show loading in main area.
    mainTabs.innerHTML = '';
    mainContent.innerHTML = `
      <div class="fp-placeholder">
        <div class="fp-spinner"></div>
        <p>Loading panel data…</p>
      </div>`;

    try {
      const resp = await fetch(`${API}/${encodeURIComponent(requestId)}`, {
        headers: { Accept: 'application/json' },
      });
      if (!resp.ok) {
        mainContent.innerHTML = `<div class="fp-placeholder"><p style="color:#ff4757">Request not found (${resp.status}).</p></div>`;
        return;
      }
      panelData = await resp.json();
      renderTabs();
      activateTab(activeTab || firstTabId());
    } catch (err) {
      mainContent.innerHTML = `<div class="fp-placeholder"><p style="color:#ff4757">Fetch failed: ${escHtml(err.message)}</p></div>`;
    }
  }

  // ─── Render panel tabs ────────────────────────────────────────────────────
  function renderTabs() {
    if (!panelData) return;
    const panels = panelData.panels || {};

    mainTabs.innerHTML = Object.entries(panels).map(([id, data]) => {
      const isActive = id === activeTab ? ' fp-tab-active' : '';
      return `
        <div class="fp-tab${isActive}" data-panel="${escAttr(id)}">
          <span class="fp-tab-title">${escHtml(tabTitle(id))}</span>
          <span class="fp-tab-badge">${escHtml(tabBadge(id, data))}</span>
        </div>`;
    }).join('');

    mainTabs.querySelectorAll('.fp-tab').forEach(tab => {
      tab.addEventListener('click', () => activateTab(tab.dataset.panel));
    });
  }

  function activateTab(tabId) {
    if (!tabId || !panelData) return;
    activeTab = tabId;

    mainTabs.querySelectorAll('.fp-tab').forEach(t => {
      t.classList.toggle('fp-tab-active', t.dataset.panel === tabId);
    });

    const data = (panelData.panels || {})[tabId];
    mainContent.innerHTML = `<div class="fp-main-content-inner">${renderPanel(tabId, data)}</div>`;
  }

  function firstTabId() {
    const panels = panelData && panelData.panels;
    return panels ? Object.keys(panels)[0] || null : null;
  }

  // ─── Tab metadata ─────────────────────────────────────────────────────────
  const TAB_TITLES = {
    sql: 'SQL', request: 'Request', response: 'Response',
    performance: 'Performance', logging: 'Logging',
    cache: 'Cache', headers: 'Headers',
  };

  function tabTitle(id) { return TAB_TITLES[id] || id; }

  function tabBadge(id, data) {
    switch (id) {
      case 'sql':         return `${data.total_queries}q ${Math.round(data.total_duration_ms)}ms`;
      case 'request':     return data.method || '?';
      case 'response':    return String(data.status_code || '?');
      case 'performance': return `${Math.round(data.total_ms || 0)}ms`;
      case 'logging':     return data.total > 0 ? `${data.total} ⚠` : '0';
      case 'cache':       return data.hit_rate !== undefined ? `${data.hit_rate}%` : '—';
      case 'headers':     return String((data.total_request_headers || 0) + (data.total_response_headers || 0));
      default:            return '';
    }
  }

  // ─── Panel renderers ──────────────────────────────────────────────────────
  function renderPanel(id, data) {
    if (!data) return '<div class="fp-empty">No data available.</div>';
    switch (id) {
      case 'sql':         return renderSQL(data);
      case 'request':     return renderRequest(data);
      case 'response':    return renderResponse(data);
      case 'performance': return renderPerformance(data);
      case 'logging':     return renderLogging(data);
      case 'cache':       return renderCache(data);
      case 'headers':     return renderHeaders(data);
      default:            return renderGeneric(data);
    }
  }

  function renderSQL(data) {
    if (!data.queries || data.queries.length === 0)
      return '<div class="fp-empty">No SQL queries executed.</div>';

    const summary = `<h3>${data.total_queries} quer${data.total_queries === 1 ? 'y' : 'ies'} — ${data.total_duration_ms.toFixed(2)}ms total</h3>`;

    const queries = data.queries.map(q => {
      const slowClass = q.is_slow ? ' fp-slow-query' : '';
      const durClass  = q.is_slow ? ' fp-slow' : '';
      return `
        <div class="fp-query-block${slowClass}">
          <div class="fp-query-header">
            <span class="fp-query-duration${durClass}">${q.duration_ms.toFixed(2)}ms</span>
            <span class="fp-query-location">${escHtml(q.location)}</span>
          </div>
          <pre class="fp-query-sql">${highlightSQL(escHtml(q.sql_formatted || q.sql))}</pre>
        </div>`;
    }).join('');

    return summary + queries;
  }

  function renderRequest(data) {
    const rows = [['Method', data.method], ['URL', data.url], ['Path', data.path]];
    if (data.path_params  && Object.keys(data.path_params).length)  rows.push(['Path Params',  JSON.stringify(data.path_params)]);
    if (data.query_params && Object.keys(data.query_params).length) rows.push(['Query Params', JSON.stringify(data.query_params)]);
    if (data.cookies      && Object.keys(data.cookies).length)      rows.push(['Cookies',      JSON.stringify(data.cookies)]);
    if (data.body != null) rows.push(['Body', JSON.stringify(data.body, null, 2)]);

    return `<h3>Request</h3>
      <table class="fp-table fp-kv"><tbody>
        ${rows.map(([k, v]) => `<tr><td>${escHtml(k)}</td><td><code>${escHtml(String(v))}</code></td></tr>`).join('')}
      </tbody></table>`;
  }

  function renderResponse(data) {
    const rows = [
      ['Status', data.status_code],
      ['Content-Type', data.content_type || '—'],
      ['Size', data.content_length != null ? `${data.content_length} bytes` : 'unknown'],
    ];
    return `<h3>Response</h3>
      <table class="fp-table fp-kv"><tbody>
        ${rows.map(([k, v]) => `<tr><td>${escHtml(k)}</td><td><code>${escHtml(String(v))}</code></td></tr>`).join('')}
      </tbody></table>`;
  }

  function renderPerformance(data) {
    return `
      <div class="fp-perf-grid">
        <div class="fp-perf-card">
          <span class="fp-perf-value">${data.total_ms.toFixed(1)}ms</span>
          <span class="fp-perf-label">Total Time</span>
        </div>
        <div class="fp-perf-card">
          <span class="fp-perf-value">${data.cpu_ms.toFixed(1)}ms</span>
          <span class="fp-perf-label">CPU Time</span>
        </div>
        <div class="fp-perf-card">
          <span class="fp-perf-value">${data.panel_overhead_ms.toFixed(1)}ms</span>
          <span class="fp-perf-label">Panel Overhead</span>
        </div>
      </div>`;
  }

  function renderLogging(data) {
    if (!data.records || data.records.length === 0)
      return '<div class="fp-empty">No warnings or errors during this request.</div>';

    const records = data.records.map(r => `
      <div class="fp-log-record">
        <span class="fp-log-level ${escHtml(r.level)}">${escHtml(r.level)}</span>
        <div class="fp-log-body">
          <div class="fp-log-message">${escHtml(r.message)}</div>
          <div class="fp-log-location">${escHtml(r.logger)} · ${escHtml(r.location)}</div>
          ${r.exc_text ? `<pre class="fp-log-exc">${escHtml(r.exc_text)}</pre>` : ''}
        </div>
      </div>`).join('');

    return `<h3>${data.total} record${data.total === 1 ? '' : 's'} — ${data.warning_count} warning${data.warning_count === 1 ? '' : 's'}, ${data.error_count} error${data.error_count === 1 ? '' : 's'}</h3>${records}`;
  }

  function renderCache(data) {
    const stats = `
      <div class="fp-cache-stats">
        <div class="fp-cache-stat"><span class="fp-cache-stat-value">${data.hit_rate}%</span><span class="fp-cache-stat-label">Hit Rate</span></div>
        <div class="fp-cache-stat"><span class="fp-cache-stat-value fp-op-get">${data.hits}</span><span class="fp-cache-stat-label">Hits</span></div>
        <div class="fp-cache-stat"><span class="fp-cache-stat-value fp-op-miss">${data.misses}</span><span class="fp-cache-stat-label">Misses</span></div>
        <div class="fp-cache-stat"><span class="fp-cache-stat-value fp-op-set">${data.sets}</span><span class="fp-cache-stat-label">Sets</span></div>
        <div class="fp-cache-stat"><span class="fp-cache-stat-value fp-op-del">${data.deletes}</span><span class="fp-cache-stat-label">Deletes</span></div>
      </div>`;

    if (!data.events || data.events.length === 0)
      return stats + '<div class="fp-empty">No cache operations recorded.</div>';

    const rows = data.events.map(e => {
      const opClass  = `fp-op-${e.operation === 'get' ? (e.hit ? 'get' : 'miss') : e.operation}`;
      const hitLabel = e.operation === 'get' ? (e.hit ? ' (hit)' : ' (miss)') : '';
      return `<tr><td class="${opClass}">${escHtml(e.operation.toUpperCase())}${escHtml(hitLabel)}</td><td><code>${escHtml(e.key)}</code></td></tr>`;
    }).join('');

    return stats + `<h3>Events</h3>
      <table class="fp-table">
        <thead><tr><th>Operation</th><th>Key</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  function renderHeaders(data) {
    const makeTable = (title, headers) => {
      if (!headers || headers.length === 0) return '';
      const rows = headers.map(h =>
        `<tr><td>${escHtml(h.name)}</td><td><code>${escHtml(h.value)}</code></td></tr>`
      ).join('');
      return `<h3>${escHtml(title)} (${headers.length})</h3>
        <table class="fp-table fp-kv"><tbody>${rows}</tbody></table>`;
    };
    return makeTable('Request Headers', data.request_headers) +
           makeTable('Response Headers', data.response_headers);
  }

  function renderGeneric(data) {
    return `<pre style="font-size:11px;color:#e0e0e0;white-space:pre-wrap">${escHtml(JSON.stringify(data, null, 2))}</pre>`;
  }

  // ─── Helpers ──────────────────────────────────────────────────────────────
  function showPlaceholder() {
    mainTabs.innerHTML = '';
    mainContent.innerHTML = `
      <div class="fp-placeholder">
        <span class="fp-placeholder-icon">⚡</span>
        <p>Select a request to inspect it.</p>
      </div>`;
  }

  function highlightSQL(sql) {
    return sql.replace(SQL_KEYWORDS, '<span class="fp-sql-keyword">$1</span>');
  }

  function methodCssClass(method) {
    const m = (method || '').toUpperCase();
    if (m === 'GET')    return 'fp-method-GET';
    if (m === 'POST')   return 'fp-method-POST';
    if (m === 'PUT')    return 'fp-method-PUT';
    if (m === 'PATCH')  return 'fp-method-PATCH';
    if (m === 'DELETE') return 'fp-method-DELETE';
    return 'fp-method-other';
  }

  function statusCssClass(code) {
    if (!code) return 'fp-status-0';
    if (code >= 500) return 'fp-status-5xx';
    if (code >= 400) return 'fp-status-4xx';
    if (code >= 300) return 'fp-status-3xx';
    if (code >= 200) return 'fp-status-2xx';
    return 'fp-status-0';
  }

  function escHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function escAttr(str) { return escHtml(str); }

})();
