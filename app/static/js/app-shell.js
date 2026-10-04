(function () {
  var root = document.documentElement;
  var toggle = document.getElementById('sidebar-toggle');
  var themeBtn = document.getElementById('theme-toggle');

  function setSidebar(collapsed) {
    root.classList.toggle('sidebar-collapsed', collapsed);
    localStorage.setItem('ps-tool-sidebar', collapsed ? 'collapsed' : 'expanded');
    if (toggle) {
      toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    }
  }

  setSidebar(root.classList.contains('sidebar-collapsed'));

  if (toggle) {
    toggle.addEventListener('click', function () {
      setSidebar(!root.classList.contains('sidebar-collapsed'));
    });
  }

  function applyTheme(theme) {
    root.setAttribute('data-theme', theme);
    localStorage.setItem('ps-tool-theme', theme);
  }

  if (themeBtn) {
    themeBtn.addEventListener('click', function () {
      var current = root.getAttribute('data-theme') || 'light';
      applyTheme(current === 'dark' ? 'light' : 'dark');
    });
  }
})();
