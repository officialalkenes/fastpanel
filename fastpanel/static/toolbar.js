/**
 * FastPanel Toolbar — client-side JS
 *
 * Responsibilities:
 *  1. Fetch panel data from /__fastpanel/api/{request_id}
 *  2. Render panel content into the toolbar UI
 *  3. Handle tab switching, collapse/expand, and close
 *  4. Persist toolbar state in sessionStorage
 *
 * No framework, no build step. Vanilla ES2020+. The toolbar element
 * is injected into the page by the FastPanel middleware — this script
 * runs after that injection and wires up all interactivity.
 */

(function () {
  'use strict';

  // ─── Constants ────────────────────────────────────────────────────────────
  const STORAGE_KEY_HIDDEN = 'fastpanel_hidden';
  const STORAGE_KEY_ACTIVE_TAB = 'fastpanel_active_tab';
  const STORAGE_KEY_COLLAPSED = 'fastpanel_collapsed';

  // SQL keywords for syntax highlighting in the SQL panel.
  const SQL_KEYWORDS = /\b(SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|CROSS|ON|AND|OR|NOT|IN|IS|NULL|INSERT|INTO|VALUES|UPDATE|SET|DELETE|CREATE|DROP|ALTER|TABLE|INDEX|ORDER|BY|GROUP|HAVING|LIMIT|OFFSET|DISTINCT|AS|UNION|ALL|EXISTS|BETWEEN|LIKE|CASE|WHEN|THEN|ELSE|END|WITH|RETURNING|BEGIN|COMMIT|ROLLBACK|SAVEPOINT)\b/g;

  // ─── Bootstrap ────────────────────────────────────────────────────────────
  const toolbar = document.getElementById('fastpanel-toolbar');
  if (!toolbar) return; // No toolbar injected — do nothing.

  const requestId = toolbar.dataset.requestId;
  const apiBase = toolbar.dataset.apiBase;

  if (!requestId || !apiBase) return;

  // Restore hidden state from sessionStorage — if the user closed the toolbar
  // on a previous page, keep it hidden on navigation.
  if (sessionStorage.getItem(STORAGE_KEY_HIDDEN) === '1') {
    toolbar.classList.add('fp-hidden');
    return;
  }

  // Restore collapsed state.
  if (sessionStorage.getItem(STORAGE_KEY_COLLAPSED) === '1') {
    toolbar.classList.add('fp-collapsed');
  }

  // ─── DOM refs ─────────────────────────────────────────────────────────────
  const tabbar = document.getElementById('fp-tabbar');
  const content = document.getElementById('fp-content');
  const toggleBtn = document.getElementById('fp-toggle');
  const closeBtn = document.getElementById('fp-close');

  // ─── State ────────────────────────────────────────────────────────────────
  let panelData = null;
  let activePanel = sessionStorage.getItem(STORAGE_KEY_ACTIVE_TAB) || null;

  // ─── Event: toggle collapse ────────────────────────────────────────────────
  toggleBtn.addEventListener('click', () => {
    const collapsed = toolbar.classList.toggle('fp-collapsed');
    sessionStorage.setItem(STORAGE_KEY_COLLAPSED, collapsed ? '1' : '0');
  });

  // ─── Event: close toolbar ─────────────────────────────────────────────────
  closeBtn.addEventListener('click', () => {
    toolbar.classList.add('fp-hidden');
    sessionStorage.setItem(STORAGE_KEY_HIDDEN, '1');
  });

  // ─── Fetch panel data ─────────────────────────────────────────────────────
  async function fetchPanelData() {
    try {
      const resp = await fetch(`${apiBase}/${requestId}`, {
        headers: { 'Accept': 'application/json' },
      });
      if (!resp.ok) {
        showError(`FastPanel API returned ${resp.status}`);
        return;
      }
      panelData = await resp.json();
      renderTabs();
      activateTab(activePanel || getFirstTabId());
    } catch (err) {
      showError(`FastPanel fetch failed: ${err.message}`);
    }
  }

  function showError(msg) {
    content.innerHTML = `<div class="fp-error">${escHtml(msg)}</div>`;
  }

  function getFirstTabId() {
    if (!panelData || !panelData.panels) return null;
    return Object.keys(panelData.panels)[0] || null;
  }

  // ─── Render tabs ──────────────────────────────────────────────────────────
  function renderTabs() {
    if (!panelData) return;

    // Update the total-time badge in the toggle button.
    const perf = panelData.panels.performance;
    const totalTime = perf ? `${Math.round(perf.total_ms)}ms` : '';
    const totalEl = toggleBtn.querySelector('.fp-total-time');
    if (totalEl) totalEl.textContent = totalTime ? `⚡ ${totalTime}` : '';

    // Remove existing dynamically created tabs (not the toggle or close).
    tabbar.querySelectorAll('.fp-tab').forEach(t => t.remove());

    const panelMeta = getPanelMeta(panelData.panels);
    const insertBefore = closeBtn;

    panelMeta.forEach(({ id, title, badge }) => {
      const tab = document.createElement('div');
      tab.className = 'fp-tab';
      tab.dataset.panel = id;
      tab.innerHTML = `
        <span class="fp-tab-title">${escHtml(title)}</span>
        <span class="fp-tab-badge">${escHtml(badge)}</span>
      `;
      tab.addEventListener('click', () => {
        if (toolbar.classList.contains('fp-collapsed')) {
          toolbar.classList.remove('fp-collapsed');
          sessionStorage.setItem(STORAGE_KEY_COLLAPSED, '0');
        }
        activateTab(id);
      });
      tabbar.insertBefore(tab, insertBefore);
    });
  }

  function getPanelMeta(panels) {
    const meta = [];
    const titles = {
      sql: 'SQL', request: 'Request', response: 'Response',
      performance: 'Performance', logging: 'Logging',
      cache: 'Cache', headers: 'Headers',
    };

    Object.entries(panels).forEach(([id, data]) => {
      meta.push({
        id,
        title: titles[id] || id,
        badge: getPanelBadge(id, data),
      });
    });
    return meta;
  }

  function getPanelBadge(id, data) {
    switch (id) {
      case 'sql':
        return `${data.total_queries}q ${Math.round(data.total_duration_ms)}ms`;
      case 'request':
        return data.method || '?';
      case 'response':
        return String(data.status_code || '?');
      case 'performance':
        return `${Math.round(data.total_ms || 0)}ms`;
      case 'logging':
        return data.total > 0 ? `${data.total} ⚠` : '0';
      case 'cache':
        return data.hit_rate !== undefined ? `${data.hit_rate}%` : '—';
      case 'headers':
        return String((data.total_request_headers || 0) + (data.total_response_headers || 0));
      default:
        return '';
    }
  }

  // ─── Tab activation ───────────────────────────────────────────────────────
  function activateTab(panelId) {
    if (!panelId || !panelData) return;

    // Deactivate all tabs.
    tabbar.querySelectorAll('.fp-tab').forEach(t => t.classList.remove('fp-tab-active'));

    // Activate the target tab.
    const tab = tabbar.querySelector(`[data-panel="${panelId}"]`);
    if (tab) tab.classList.add('fp-tab-active');

    activePanel = panelId;
    sessionStorage.setItem(STORAGE_KEY_ACTIVE_TAB, panelId);

    // Render the panel content.
    content.innerHTML = '';
    const panel = document.createElement('div');
    panel.className = 'fp-panel fp-panel-active';
    panel.innerHTML = renderPanel(panelId, panelData.panels[panelId]);
    content.appendChild(panel);
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
    if (!data.queries || data.queries.length === 0) {
      return '<div class="fp-empty">No SQL queries executed.</div>';
    }

    const summary = `
      <h3>${data.total_queries} quer${data.total_queries === 1 ? 'y' : 'ies'} — ${data.total_duration_ms.toFixed(2)}ms total</h3>
    `;

    const queries = data.queries.map((q, i) => {
      const slowClass = q.is_slow ? ' fp-slow-query' : '';
      const durClass = q.is_slow ? ' fp-slow' : '';
      return `
        <div class="fp-query-block${slowClass}">
          <div class="fp-query-header">
            <span class="fp-query-duration${durClass}">${q.duration_ms.toFixed(2)}ms</span>
            <span class="fp-query-location">${escHtml(q.location)}</span>
          </div>
          <pre class="fp-query-sql">${highlightSQL(escHtml(q.sql_formatted || q.sql))}</pre>
        </div>
      `;
    }).join('');

    return summary + queries;
  }

  function renderRequest(data) {
    const rows = [
      ['Method', data.method],
      ['URL', data.url],
      ['Path', data.path],
    ];

    if (data.path_params && Object.keys(data.path_params).length > 0) {
      rows.push(['Path Params', JSON.stringify(data.path_params)]);
    }
    if (data.query_params && Object.keys(data.query_params).length > 0) {
      rows.push(['Query Params', JSON.stringify(data.query_params)]);
    }
    if (data.cookies && Object.keys(data.cookies).length > 0) {
      rows.push(['Cookies', JSON.stringify(data.cookies)]);
    }
    if (data.body !== null && data.body !== undefined) {
      rows.push(['Body', JSON.stringify(data.body, null, 2)]);
    }

    return `
      <h3>Request</h3>
      <table class="fp-table fp-kv">
        <tbody>${rows.map(([k, v]) => `
          <tr><td>${escHtml(k)}</td><td><code>${escHtml(String(v))}</code></td></tr>
        `).join('')}</tbody>
      </table>
    `;
  }

  function renderResponse(data) {
    const rows = [
      ['Status', data.status_code],
      ['Content-Type', data.content_type || '—'],
      ['Size', data.content_length !== null ? `${data.content_length} bytes` : 'unknown'],
    ];

    return `
      <h3>Response</h3>
      <table class="fp-table fp-kv">
        <tbody>${rows.map(([k, v]) => `
          <tr><td>${escHtml(k)}</td><td><code>${escHtml(String(v))}</code></td></tr>
        `).join('')}</tbody>
      </table>
    `;
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
      </div>
    `;
  }

  function renderLogging(data) {
    if (!data.records || data.records.length === 0) {
      return '<div class="fp-empty">No warnings or errors during this request.</div>';
    }

    const records = data.records.map(r => `
      <div class="fp-log-record">
        <span class="fp-log-level ${escHtml(r.level)}">${escHtml(r.level)}</span>
        <div class="fp-log-body">
          <div class="fp-log-message">${escHtml(r.message)}</div>
          <div class="fp-log-location">${escHtml(r.logger)} · ${escHtml(r.location)}</div>
          ${r.exc_text ? `<pre class="fp-log-exc">${escHtml(r.exc_text)}</pre>` : ''}
        </div>
      </div>
    `).join('');

    return `
      <h3>${data.total} record${data.total === 1 ? '' : 's'} — ${data.warning_count} warning${data.warning_count === 1 ? '' : 's'}, ${data.error_count} error${data.error_count === 1 ? '' : 's'}</h3>
      ${records}
    `;
  }

  function renderCache(data) {
    const stats = `
      <div class="fp-cache-stats">
        <div class="fp-cache-stat">
          <span class="fp-cache-stat-value">${data.hit_rate}%</span>
          <span class="fp-cache-stat-label">Hit Rate</span>
        </div>
        <div class="fp-cache-stat">
          <span class="fp-cache-stat-value fp-op-get">${data.hits}</span>
          <span class="fp-cache-stat-label">Hits</span>
        </div>
        <div class="fp-cache-stat">
          <span class="fp-cache-stat-value fp-op-miss">${data.misses}</span>
          <span class="fp-cache-stat-label">Misses</span>
        </div>
        <div class="fp-cache-stat">
          <span class="fp-cache-stat-value fp-op-set">${data.sets}</span>
          <span class="fp-cache-stat-label">Sets</span>
        </div>
        <div class="fp-cache-stat">
          <span class="fp-cache-stat-value fp-op-del">${data.deletes}</span>
          <span class="fp-cache-stat-label">Deletes</span>
        </div>
      </div>
    `;

    if (!data.events || data.events.length === 0) {
      return stats + '<div class="fp-empty">No cache operations recorded.</div>';
    }

    const rows = data.events.map(e => {
      const opClass = `fp-op-${e.operation === 'get' ? (e.hit ? 'get' : 'miss') : e.operation}`;
      const hitLabel = e.operation === 'get' ? (e.hit ? ' (hit)' : ' (miss)') : '';
      return `<tr>
        <td class="${opClass}">${escHtml(e.operation.toUpperCase())}${escHtml(hitLabel)}</td>
        <td><code>${escHtml(e.key)}</code></td>
      </tr>`;
    }).join('');

    return stats + `
      <h3>Events</h3>
      <table class="fp-table">
        <thead><tr><th>Operation</th><th>Key</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    `;
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

    return (
      makeTable('Request Headers', data.request_headers) +
      makeTable('Response Headers', data.response_headers)
    );
  }

  function renderGeneric(data) {
    return `<pre style="font-size:11px;color:var(--fp-text)">${escHtml(JSON.stringify(data, null, 2))}</pre>`;
  }

  // ─── SQL syntax highlighting ───────────────────────────────────────────────
  function highlightSQL(sql) {
    // Replace SQL keywords with styled spans.
    // The input is already HTML-escaped, so we only need to add spans.
    return sql.replace(SQL_KEYWORDS, '<span class="fp-sql-keyword">$1</span>');
  }

  // ─── Utilities ────────────────────────────────────────────────────────────
  function escHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // ─── Init ─────────────────────────────────────────────────────────────────
  // Show loading state in the content area while fetching.
  content.innerHTML = '<div class="fp-loading">Loading panel data…</div>';

  // Fetch panel data asynchronously — doesn't block page render.
  fetchPanelData();
})();
