(function () {
  var FILTERS_STORAGE_KEY = 'ps-tool-browse-filters';

  function inactiveStatuses() {
    var statusEl = document.getElementById('browse-filter-status');
    if (!statusEl) {
      return ['pending', 'not_run', 'disabled', 'killed', 'unknown'];
    }
    var raw = statusEl.getAttribute('data-inactive-statuses') || '';
    return raw
      .split(',')
      .map(function (s) {
        return s.trim();
      })
      .filter(Boolean);
  }

  function getPane() {
    return document.querySelector('.browse-tree-pane');
  }

  function rowMatchesName(row, query) {
    if (!query) {
      return true;
    }
    var name = (row.getAttribute('data-job-name') || '').toLowerCase();
    return name.indexOf(query.toLowerCase()) !== -1;
  }

  function rowMatchesStatus(row, statusFilter) {
    if (!statusFilter || statusFilter === 'all') {
      return true;
    }
    var status = row.getAttribute('data-status') || '';
    if (statusFilter === 'inactive') {
      return inactiveStatuses().indexOf(status) !== -1;
    }
    return status === statusFilter;
  }

  function directChildNodes(node) {
    var details = node.querySelector(':scope > details.browse-tree-branch');
    if (!details) {
      return [];
    }
    var wrap = details.querySelector(':scope > .browse-tree-children');
    if (!wrap) {
      return [];
    }
    return Array.prototype.slice.call(wrap.querySelectorAll(':scope > .browse-tree-node'));
  }

  function setRowVisible(row, visible) {
    if (!row) {
      return;
    }
    if (visible) {
      row.removeAttribute('hidden');
      row.classList.remove('browse-filter-hidden');
    } else {
      row.setAttribute('hidden', '');
      row.classList.add('browse-filter-hidden');
    }
  }

  function applyNodeVisibility(node, parentSelfMatch) {
    var row = node.querySelector(':scope > .browse-job-row');
    if (!row) {
      return false;
    }

    var nameOk = rowMatchesName(row, window.psBrowseFilterQuery || '');
    var statusOk = rowMatchesStatus(row, window.psBrowseFilterStatus || 'all');
    var selfMatch = nameOk && statusOk;

    var children = directChildNodes(node);
    var anyChildVisible = false;
    for (var i = 0; i < children.length; i++) {
      if (applyNodeVisibility(children[i], selfMatch)) {
        anyChildVisible = true;
      }
    }

    var visible;
    if (parentSelfMatch) {
      visible = statusOk || anyChildVisible;
    } else {
      visible = selfMatch || anyChildVisible;
    }

    setRowVisible(row, visible);

    var details = node.querySelector(':scope > details.browse-tree-branch');
    if (details && anyChildVisible) {
      details.open = true;
    }

    return visible;
  }

  function updateEmptyState(pane, anyVisible) {
    var body = pane.querySelector('.browse-tree-body');
    if (!body) {
      return;
    }
    var empty = body.querySelector('.browse-filter-empty');
    if (!anyVisible) {
      if (!empty) {
        empty = document.createElement('p');
        empty.className = 'browse-filter-empty muted';
        empty.textContent = 'No jobs match the current filters.';
        body.appendChild(empty);
      }
      empty.removeAttribute('hidden');
    } else if (empty) {
      empty.setAttribute('hidden', '');
    }
  }

  function applyBrowseFilters() {
    var pane = getPane();
    if (!pane) {
      return;
    }
    var searchEl = document.getElementById('browse-filter-search');
    var statusEl = document.getElementById('browse-filter-status');
    window.psBrowseFilterQuery = searchEl ? searchEl.value.trim() : '';
    window.psBrowseFilterStatus = statusEl ? statusEl.value : 'all';

    var body = pane.querySelector('.browse-tree-body');
    if (!body) {
      return;
    }

    var roots = Array.prototype.slice.call(body.querySelectorAll(':scope > .browse-tree-node'));
    var anyVisible = false;
    for (var i = 0; i < roots.length; i++) {
      if (applyNodeVisibility(roots[i], false)) {
        anyVisible = true;
      }
    }
    updateEmptyState(pane, anyVisible);
  }

  function updateFiltersSummary() {
    var hint = document.getElementById('browse-filters-summary');
    var searchEl = document.getElementById('browse-filter-search');
    var statusEl = document.getElementById('browse-filter-status');
    if (!hint) {
      return;
    }
    var parts = [];
    if (searchEl && searchEl.value.trim()) {
      parts.push('Search: ' + searchEl.value.trim());
    }
    if (statusEl && statusEl.value && statusEl.value !== 'all') {
      var label = statusEl.options[statusEl.selectedIndex];
      parts.push(label ? label.text.trim() : statusEl.value);
    }
    hint.textContent = parts.length ? parts.join(' · ') : 'Search & status';
  }

  function setFiltersCollapsed(collapsed) {
    var panel = document.getElementById('browse-filters-panel');
    var btn = document.getElementById('browse-filters-toggle');
    var hint = document.getElementById('browse-filters-summary');
    if (!panel || !btn) {
      return;
    }
    panel.classList.toggle('is-collapsed', collapsed);
    btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    if (hint) {
      if (collapsed) {
        hint.removeAttribute('hidden');
      } else {
        hint.setAttribute('hidden', '');
      }
    }
    localStorage.setItem(FILTERS_STORAGE_KEY, collapsed ? 'collapsed' : 'expanded');
    updateFiltersSummary();
  }

  function bindFiltersPanel() {
    var panel = document.getElementById('browse-filters-panel');
    var btn = document.getElementById('browse-filters-toggle');
    if (!panel || !btn || panel.getAttribute('data-browse-filters-panel-bound') === 'true') {
      return;
    }
    panel.setAttribute('data-browse-filters-panel-bound', 'true');

    var stored = localStorage.getItem(FILTERS_STORAGE_KEY);
    setFiltersCollapsed(stored === 'collapsed');

    btn.addEventListener('click', function () {
      setFiltersCollapsed(!panel.classList.contains('is-collapsed'));
    });

    updateFiltersSummary();
  }

  function bindPane(pane) {
    if (!pane || pane.getAttribute('data-browse-filters-bound') === 'true') {
      return;
    }
    pane.setAttribute('data-browse-filters-bound', 'true');

    bindFiltersPanel();

    var searchEl = document.getElementById('browse-filter-search');
    var statusEl = document.getElementById('browse-filter-status');
    if (searchEl) {
      searchEl.addEventListener('input', function () {
        updateFiltersSummary();
        applyBrowseFilters();
      });
    }
    if (statusEl) {
      statusEl.addEventListener('change', function () {
        updateFiltersSummary();
        applyBrowseFilters();
      });
    }

    var body = pane.querySelector('.browse-tree-body');
    if (body && typeof MutationObserver !== 'undefined') {
      var observer = new MutationObserver(function () {
        applyBrowseFilters();
      });
      observer.observe(body, { childList: true, subtree: true });
      pane._browseFilterObserver = observer;
    }

    applyBrowseFilters();
  }

  function initBrowseFilters() {
    var pane = getPane();
    if (pane) {
      bindPane(pane);
    }
  }

  window.psBrowseFiltersInit = initBrowseFilters;
  window.psBrowseApplyFilters = applyBrowseFilters;

  document.addEventListener('htmx:afterSwap', function (evt) {
    var target = evt.detail && evt.detail.target;
    if (!target) {
      return;
    }
    if (
      target.classList &&
      (target.classList.contains('browse-tree-children') ||
        target.id === 'browse-output' ||
        target.closest('.browse-tree-pane'))
    ) {
      initBrowseFilters();
      applyBrowseFilters();
    }
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initBrowseFilters);
  } else {
    initBrowseFilters();
  }
})();
