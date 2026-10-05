(function () {
  var root = document.documentElement;
  var toggle = document.getElementById('sidebar-toggle');
  var themeBtn = document.getElementById('theme-toggle');
  var feedback = document.getElementById('app-feedback');

  function remember(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* Private storage may be unavailable. */ }
  }

  function setSidebar(collapsed) {
    root.classList.toggle('sidebar-collapsed', collapsed);
    remember('ps-tool-sidebar', collapsed ? 'collapsed' : 'expanded');
    if (toggle) {
      toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    }
  }

  setSidebar(root.classList.contains('sidebar-collapsed'));
  window.matchMedia('(max-width: 800px)').addEventListener('change', function (event) {
    if (event.matches) setSidebar(true);
  });

  if (toggle) {
    toggle.addEventListener('click', function () {
      setSidebar(!root.classList.contains('sidebar-collapsed'));
    });
  }

  function applyTheme(theme) {
    root.setAttribute('data-theme', theme);
    remember('ps-tool-theme', theme);
    if (themeBtn) {
      themeBtn.setAttribute('aria-label', theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
    }
  }

  if (themeBtn) {
    applyTheme(root.getAttribute('data-theme') || 'light');
    themeBtn.addEventListener('click', function () {
      var current = root.getAttribute('data-theme') || 'light';
      applyTheme(current === 'dark' ? 'light' : 'dark');
    });
  }

  // Runtime tree depth is data, not a hardcoded presentation value.
  function applyTreeDepth(scope) {
    scope.querySelectorAll('.browse-tree-node[data-depth]').forEach(function (node) {
      node.style.setProperty('--browse-depth', String(Math.max(0, Number(node.dataset.depth) || 0)));
    });
  }
  applyTreeDepth(document);
  document.addEventListener('htmx:afterSwap', function (event) {
    var target = event.detail && event.detail.target;
    if (target) applyTreeDepth(target);
  });

  document.addEventListener('keydown', function (event) {
    var search = document.getElementById('global-search');
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k' && search && !search.disabled) {
      event.preventDefault();
      search.focus();
    }
    if (event.key === 'Escape') {
      var results = document.getElementById('search-results');
      if (results) results.innerHTML = '';
      if (window.psBrowseClosePanel && !event.target.closest('.browse-status-picker')) window.psBrowseClosePanel();
    }
  });
  document.addEventListener('click', function (event) {
    if (!event.target.closest('.search-bar')) {
      var results = document.getElementById('search-results');
      if (results) results.innerHTML = '';
    }
  });
  document.addEventListener('htmx:beforeRequest', function () {
    if (feedback) feedback.hidden = true;
  });
  function showRequestError(event) {
    if (!feedback) return;
    var message = 'Unable to load data. Check the connection and try again.';
    try {
      var detail = JSON.parse(event.detail.xhr.responseText).detail;
      if (typeof detail === 'string') message = detail;
    } catch (e) { /* Use the plain-language fallback. */ }
    feedback.textContent = message;
    feedback.hidden = false;
  }
  document.addEventListener('htmx:responseError', showRequestError);
  document.addEventListener('htmx:sendError', showRequestError);
})();
