(function () {
  var STORAGE_KEY = 'ps-tool-browse-form-collapsed';

  function panelEl() {
    return document.getElementById('browse-env-panel');
  }

  function summaryEl() {
    return document.getElementById('browse-env-summary');
  }

  function toggleBtn() {
    return document.getElementById('browse-env-toggle');
  }

  function selectedLabel(selectId) {
    var el = document.getElementById(selectId);
    if (!el || el.tagName !== 'SELECT') {
      return '';
    }
    var opt = el.options[el.selectedIndex];
    return opt ? opt.text.trim() : '';
  }

  function refreshSummary() {
    var summary = summaryEl();
    if (!summary) {
      return;
    }
    var env = selectedLabel('browse-env');
    var sched = selectedLabel('browse-scheduler');
    var parts = [];
    if (env) {
      parts.push(env);
    }
    if (sched) {
      parts.push(sched);
    }
    var schedVal = document.getElementById('browse-scheduler');
    var schedType = schedVal ? schedVal.value : '';
    if (schedType === 'process_scheduler') {
      var topo = document.getElementById('browse-topology');
      if (topo && topo.value) {
        parts.push(topo.value);
      }
    } else {
      var asOfHidden = document.getElementById('browse-as-of');
      var asOfVisible = document.getElementById('browse-as-of-visible');
      var asOf = (asOfVisible && asOfVisible.value) || (asOfHidden && asOfHidden.value);
      if (asOf) {
        parts.push(asOf);
      }
    }
    summary.textContent = parts.length ? parts.join(' · ') : 'Select context and load tree';
  }

  function setCollapsed(collapsed) {
    var panel = panelEl();
    var btn = toggleBtn();
    if (!panel || !btn) {
      return;
    }
    panel.classList.toggle('is-collapsed', collapsed);
    btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    btn.setAttribute(
      'aria-label',
      collapsed ? 'Expand browse environment panel' : 'Collapse browse environment panel'
    );
    try {
      localStorage.setItem(STORAGE_KEY, collapsed ? 'collapsed' : 'expanded');
    } catch (e) {
      /* ignore */
    }
    refreshSummary();
  }

  function bindFormListeners() {
    var form = document.getElementById('browse-form');
    if (!form || form.getAttribute('data-browse-env-bound') === 'true') {
      return;
    }
    form.setAttribute('data-browse-env-bound', 'true');
    form.addEventListener('change', refreshSummary);
    form.addEventListener('input', refreshSummary);
  }

  function initBrowseEnvPanel() {
    var panel = panelEl();
    var btn = toggleBtn();
    if (!panel || !btn) {
      return;
    }
    if (btn.getAttribute('data-bound') === 'true') {
      refreshSummary();
      return;
    }
    btn.setAttribute('data-bound', 'true');
    btn.addEventListener('click', function () {
      setCollapsed(!panel.classList.contains('is-collapsed'));
    });
    bindFormListeners();
    var stored = null;
    try {
      stored = localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      stored = null;
    }
    setCollapsed(stored === 'collapsed');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initBrowseEnvPanel);
  } else {
    initBrowseEnvPanel();
  }

  document.body.addEventListener('htmx:afterSwap', function (evt) {
    var target = evt.detail && evt.detail.target;
    if (!target) {
      return;
    }
    if (target.id === 'browse-context-fields' || target.id === 'browse-output') {
      bindFormListeners();
      refreshSummary();
    }
  });

  window.psBrowseEnvPanelInit = initBrowseEnvPanel;
})();
