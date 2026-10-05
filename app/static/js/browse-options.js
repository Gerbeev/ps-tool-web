(function () {
  var STORAGE_KEY = 'ps-tool-browse-context';

  function panel() {
    return document.getElementById('browse-context-panel');
  }

  function toggleBtn() {
    return document.getElementById('browse-context-toggle');
  }

  function selectedLabel(selectEl) {
    if (!selectEl || selectEl.selectedIndex < 0) {
      return '';
    }
    var opt = selectEl.options[selectEl.selectedIndex];
    return opt ? opt.text.trim() : '';
  }

  function updateSummary() {
    var hint = document.getElementById('browse-context-summary');
    if (!hint) {
      return;
    }
    var env = document.getElementById('browse-env');
    var scheduler = document.getElementById('browse-scheduler');
    var envLabel = selectedLabel(env);
    var schedLabel = selectedLabel(scheduler);
    var parts = [];
    if (envLabel) {
      parts.push(envLabel);
    }
    if (schedLabel) {
      parts.push(schedLabel);
    }
    hint.textContent = parts.join(' · ');
  }

  function setCollapsed(collapsed) {
    var el = panel();
    var btn = toggleBtn();
    if (!el || !btn) {
      return;
    }
    el.classList.toggle('is-collapsed', collapsed);
    btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    var hint = document.getElementById('browse-context-summary');
    if (hint) {
      if (collapsed) {
        hint.removeAttribute('hidden');
      } else {
        hint.setAttribute('hidden', '');
      }
    }
    localStorage.setItem(STORAGE_KEY, collapsed ? 'collapsed' : 'expanded');
    updateSummary();
  }

  function restoreOpenState() {
    var stored = localStorage.getItem(STORAGE_KEY);
    setCollapsed(stored === 'collapsed');
  }

  function bind() {
    var el = panel();
    var btn = toggleBtn();
    if (!el || !btn || el.getAttribute('data-browse-context-bound') === 'true') {
      return;
    }
    el.setAttribute('data-browse-context-bound', 'true');

    restoreOpenState();

    btn.addEventListener('click', function () {
      setCollapsed(!el.classList.contains('is-collapsed'));
    });

    var env = document.getElementById('browse-env');
    var scheduler = document.getElementById('browse-scheduler');
    if (env) {
      env.addEventListener('change', updateSummary);
    }
    if (scheduler) {
      scheduler.addEventListener('change', updateSummary);
    }

    document.body.addEventListener('htmx:afterSwap', function (evt) {
      var target = evt.detail && evt.detail.target;
      if (target && target.id === 'browse-context-fields') {
        updateSummary();
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bind);
  } else {
    bind();
  }
})();
