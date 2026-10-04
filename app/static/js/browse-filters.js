(function () {
  var INACTIVE_STATUSES = ['pending', 'not_run', 'disabled', 'killed', 'unknown'];

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
      return INACTIVE_STATUSES.indexOf(status) !== -1;
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

  function bindPane(pane) {
    if (!pane || pane.getAttribute('data-browse-filters-bound') === 'true') {
      return;
    }
    pane.setAttribute('data-browse-filters-bound', 'true');

    var searchEl = document.getElementById('browse-filter-search');
    var statusEl = document.getElementById('browse-filter-status');
    if (searchEl) {
      searchEl.addEventListener('input', applyBrowseFilters);
    }
    if (statusEl) {
      statusEl.addEventListener('change', applyBrowseFilters);
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
