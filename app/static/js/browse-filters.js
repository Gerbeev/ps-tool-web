(function () {
  if (window.__psBrowseFiltersBootstrapped) {
    return;
  }
  window.__psBrowseFiltersBootstrapped = true;

  var pickerListenersBound = false;

  function inactiveStatuses() {
    var root = document.getElementById('browse-filter-status');
    if (!root) {
      return ['pending', 'not_run', 'disabled', 'killed', 'unknown'];
    }
    return (root.getAttribute('data-inactive-statuses') || '')
      .split(',')
      .map(function (s) {
        return s.trim();
      })
      .filter(Boolean);
  }

  function statusCheckboxes() {
    return Array.prototype.slice.call(document.querySelectorAll('.browse-status-checkbox'));
  }

  function getSelectedStatuses() {
    var checked = statusCheckboxes().filter(function (el) {
      return el.checked;
    });
    if (!checked.length) {
      return null;
    }
    return checked.map(function (el) {
      return el.value;
    });
  }

  function updatePickerLabel() {
    var labelEl = document.getElementById('browse-status-picker-label');
    if (!labelEl) {
      return;
    }
    var selected = getSelectedStatuses();
    if (!selected) {
      labelEl.textContent = 'All statuses';
      return;
    }
    if (selected.length === 1) {
      var text = selected[0];
      statusCheckboxes().forEach(function (box) {
        if (box.checked) {
          var row = box.closest('.browse-status-picker-row');
          var span = row ? row.querySelector('.browse-status-picker-row-label') : null;
          if (span) {
            text = span.textContent.trim();
          }
        }
      });
      labelEl.textContent = text;
      return;
    }
    labelEl.textContent = selected.length + ' selected';
  }

  function getPopover() {
    return document.getElementById('browse-status-picker-popover');
  }

  function getTrigger() {
    return document.getElementById('browse-status-picker-trigger');
  }

  function positionPopover() {
    var trigger = getTrigger();
    var popover = getPopover();
    if (!trigger || !popover || popover.hidden) {
      return;
    }
    var rect = trigger.getBoundingClientRect();
    var width = Math.max(rect.width, 240);
    popover.style.position = 'fixed';
    popover.style.top = Math.round(rect.bottom + 4) + 'px';
    popover.style.left = Math.round(rect.left) + 'px';
    popover.style.width = Math.round(width) + 'px';
    popover.style.zIndex = '200';
  }

  function setPopoverOpen(open) {
    var trigger = getTrigger();
    var popover = getPopover();
    if (!trigger || !popover) {
      return;
    }
    if (open) {
      popover.removeAttribute('hidden');
      trigger.setAttribute('aria-expanded', 'true');
      positionPopover();
    } else {
      popover.setAttribute('hidden', '');
      trigger.setAttribute('aria-expanded', 'false');
    }
  }

  function applyStatusPreset(preset) {
    var inactive = inactiveStatuses();
    statusCheckboxes().forEach(function (box) {
      if (preset === 'all') {
        box.checked = false;
      } else if (preset === 'inactive') {
        box.checked = inactive.indexOf(box.value) !== -1;
      }
    });
    updatePickerLabel();
    applyBrowseFilters();
  }

  function bindPickerGlobalListeners() {
    if (pickerListenersBound) {
      return;
    }
    pickerListenersBound = true;

    window.addEventListener('resize', positionPopover);
    window.addEventListener('scroll', positionPopover, true);

    document.addEventListener('click', function (e) {
      var picker = document.getElementById('browse-filter-status');
      if (!picker || picker.contains(e.target)) {
        return;
      }
      setPopoverOpen(false);
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        setPopoverOpen(false);
      }
    });
  }

  function bindStatusPicker() {
    var picker = document.getElementById('browse-filter-status');
    if (!picker || picker.getAttribute('data-browse-status-bound') === 'true') {
      return;
    }
    picker.setAttribute('data-browse-status-bound', 'true');

    bindPickerGlobalListeners();

    var trigger = getTrigger();
    if (trigger) {
      trigger.addEventListener('click', function (e) {
        e.stopPropagation();
        var open = trigger.getAttribute('aria-expanded') === 'true';
        setPopoverOpen(!open);
      });
    }

    statusCheckboxes().forEach(function (box) {
      box.addEventListener('change', function () {
        updatePickerLabel();
        applyBrowseFilters();
      });
    });

    Array.prototype.forEach.call(picker.querySelectorAll('.browse-status-picker-action'), function (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        applyStatusPreset(btn.getAttribute('data-status-preset'));
      });
    });

    updatePickerLabel();
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

  function rowMatchesStatus(row, selectedStatuses) {
    if (!selectedStatuses || !selectedStatuses.length) {
      return true;
    }
    var status = row.getAttribute('data-status') || '';
    return selectedStatuses.indexOf(status) !== -1;
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
    var statusOk = rowMatchesStatus(row, window.psBrowseFilterStatuses);
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
        empty.className = 'browse-filter-empty box__pad muted';
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
    window.psBrowseFilterQuery = searchEl ? searchEl.value.trim() : '';
    window.psBrowseFilterStatuses = getSelectedStatuses();

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

    setPopoverOpen(false);
    bindStatusPicker();

    var searchEl = document.getElementById('browse-filter-search');
    if (searchEl) {
      searchEl.addEventListener('input', applyBrowseFilters);
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
      setPopoverOpen(false);
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
