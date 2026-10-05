(function () {
  if (window.__psCompareTableFiltersBootstrapped) {
    return;
  }
  window.__psCompareTableFiltersBootstrapped = true;

  var pickerListenersBound = false;

  function categoryCheckboxes() {
    return Array.prototype.slice.call(document.querySelectorAll('.compare-category-checkbox'));
  }

  function getSelectedCategories() {
    var checked = categoryCheckboxes().filter(function (el) {
      return el.checked;
    });
    if (!checked.length) {
      return null;
    }
    return checked.map(function (el) {
      return el.value;
    });
  }

  function updateCategoryLabel() {
    var labelEl = document.getElementById('compare-category-picker-label');
    if (!labelEl) {
      return;
    }
    var selected = getSelectedCategories();
    if (!selected) {
      labelEl.textContent = 'All rows';
      return;
    }
    if (selected.length === 1) {
      categoryCheckboxes().forEach(function (box) {
        if (box.checked) {
          var row = box.closest('.browse-status-picker-row');
          var span = row ? row.querySelector('.browse-status-picker-row-label') : null;
          if (span) {
            labelEl.textContent = span.textContent.trim();
          }
        }
      });
      return;
    }
    labelEl.textContent = selected.length + ' selected';
  }

  function getPopover() {
    return document.getElementById('compare-category-picker-popover');
  }

  function getTrigger() {
    return document.getElementById('compare-category-picker-trigger');
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

  function applyCategoryPreset(preset) {
    categoryCheckboxes().forEach(function (box) {
      if (preset === 'all') {
        box.checked = false;
      } else if (preset === 'mismatches') {
        box.checked = ['status_delta', 'left_only', 'right_only', 'param_delta'].indexOf(box.value) !== -1;
      } else if (preset === 'matched') {
        box.checked = box.value === 'matched';
      } else if (preset === 'status_delta') {
        box.checked = box.value === 'status_delta';
      } else if (preset === 'left_only') {
        box.checked = box.value === 'left_only';
      } else if (preset === 'right_only') {
        box.checked = box.value === 'right_only';
      }
    });
    updateCategoryLabel();
    applyCompareTableFilters();
  }

  function bindPickerGlobalListeners() {
    if (pickerListenersBound) {
      return;
    }
    pickerListenersBound = true;
    document.addEventListener('click', function (evt) {
      var picker = document.getElementById('compare-filter-categories');
      if (!picker || picker.contains(evt.target)) {
        return;
      }
      setPopoverOpen(false);
    });
    window.addEventListener('resize', function () {
      positionPopover();
    });
    window.addEventListener('scroll', function () {
      positionPopover();
    }, true);
  }

  function bindCategoryPicker() {
    var trigger = getTrigger();
    var popover = getPopover();
    if (!trigger || !popover || trigger.getAttribute('data-compare-picker-bound') === 'true') {
      return;
    }
    trigger.setAttribute('data-compare-picker-bound', 'true');
    bindPickerGlobalListeners();

    trigger.addEventListener('click', function (evt) {
      evt.stopPropagation();
      setPopoverOpen(popover.hidden);
    });

    popover.querySelectorAll('[data-category-preset]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        applyCategoryPreset(btn.getAttribute('data-category-preset') || 'all');
        setPopoverOpen(false);
      });
    });

    categoryCheckboxes().forEach(function (box) {
      box.addEventListener('change', function () {
        updateCategoryLabel();
        applyCompareTableFilters();
      });
    });
  }

  function rowMatchesSearch(row, query) {
    if (!query) {
      return true;
    }
    var hay = (row.getAttribute('data-compare-search') || '').toLowerCase();
    var q = query.toLowerCase();
    return hay.indexOf(q) !== -1;
  }

  function rowMatchesCategories(row, categories) {
    if (!categories || !categories.length) {
      return true;
    }
    var tags = (row.getAttribute('data-compare-tags') || '').split(/\s+/).filter(Boolean);
    for (var i = 0; i < categories.length; i++) {
      if (tags.indexOf(categories[i]) !== -1) {
        return true;
      }
    }
    return false;
  }

  function setRowVisible(row, visible) {
    if (!row) {
      return;
    }
    if (visible) {
      row.removeAttribute('hidden');
      row.classList.remove('compare-filter-hidden');
    } else {
      row.setAttribute('hidden', '');
      row.classList.add('compare-filter-hidden');
    }
  }

  function updateMeta(visibleCount, totalCount, limited) {
    var meta = document.getElementById('compare-table-meta');
    if (!meta) {
      return;
    }
    var limitEl = document.getElementById('compare-filter-limit');
    var limit = limitEl ? parseInt(limitEl.value, 10) : 0;
    var text = 'Showing ' + visibleCount;
    if (limited && limit > 0) {
      text += ' of ' + totalCount + ' matching rows (page size ' + limit + ')';
    } else {
      text += ' of ' + totalCount + ' rows';
    }
    meta.textContent = text;
  }

  function updateEmptyState(anyVisible) {
    var body = document.getElementById('compare-table-body');
    if (!body) {
      return;
    }
    var empty = body.querySelector('.compare-filter-empty');
    if (!anyVisible) {
      if (!empty) {
        empty = document.createElement('tr');
        empty.className = 'compare-filter-empty';
        empty.innerHTML = '<td colspan="8" class="muted box__pad">No rows match the current filters.</td>';
        body.appendChild(empty);
      }
      empty.removeAttribute('hidden');
    } else if (empty) {
      empty.setAttribute('hidden', '');
    }
  }

  function applyCompareTableFilters() {
    var body = document.getElementById('compare-table-body');
    if (!body) {
      return;
    }
    var searchEl = document.getElementById('compare-filter-search');
    var query = searchEl ? searchEl.value.trim() : '';
    var categories = getSelectedCategories();
    var limitEl = document.getElementById('compare-filter-limit');
    var limit = limitEl ? parseInt(limitEl.value, 10) : 0;
    if (Number.isNaN(limit) || limit < 0) {
      limit = 0;
    }

    var rows = Array.prototype.slice.call(body.querySelectorAll('tr[data-compare-tags]'));
    var matched = [];
    rows.forEach(function (row) {
      if (rowMatchesSearch(row, query) && rowMatchesCategories(row, categories)) {
        matched.push(row);
      }
    });

    rows.forEach(function (row) {
      setRowVisible(row, false);
    });

    var showCount = limit > 0 ? Math.min(limit, matched.length) : matched.length;
    for (var i = 0; i < matched.length; i++) {
      setRowVisible(matched[i], i < showCount);
    }

    updateMeta(showCount, matched.length, limit > 0 && matched.length > showCount);
    updateEmptyState(showCount > 0);
  }

  function bindCompareTableFilters() {
    var root = document.querySelector('.compare-table-filters');
    if (!root || root.getAttribute('data-compare-filters-bound') === 'true') {
      return;
    }
    root.setAttribute('data-compare-filters-bound', 'true');
    setPopoverOpen(false);
    bindCategoryPicker();

    var searchEl = document.getElementById('compare-filter-search');
    if (searchEl) {
      searchEl.addEventListener('input', applyCompareTableFilters);
    }
    var limitEl = document.getElementById('compare-filter-limit');
    if (limitEl) {
      limitEl.addEventListener('change', applyCompareTableFilters);
    }

    applyCompareTableFilters();
  }

  function initCompareTableFilters() {
    bindCompareTableFilters();
    applyCompareTableFilters();
  }

  window.psCompareTableApplyPreset = applyCategoryPreset;
  window.psCompareTableFiltersInit = initCompareTableFilters;
  window.psCompareTableApplyFilters = applyCompareTableFilters;

  document.addEventListener('htmx:afterSwap', function (evt) {
    var target = evt.detail && evt.detail.target;
    if (!target) {
      return;
    }
    if (target.id === 'compare-table-panel' || target.id === 'compare-output') {
      setPopoverOpen(false);
      initCompareTableFilters();
    }
  });

  document.addEventListener('click', function (evt) {
    var card = evt.target.closest('[data-compare-preset]');
    if (!card) {
      return;
    }
    var preset = card.getAttribute('data-compare-preset');
    if (preset) {
      applyCategoryPreset(preset);
    }
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCompareTableFilters);
  } else {
    initCompareTableFilters();
  }
})();
