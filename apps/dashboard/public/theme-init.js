(function () {
  /* First-paint theme resolve. Runs synchronously before React hydration so
     users never see a light flash before dark mode kicks in. The brand palette
     is locked to Nova/zinc + Juno oxblood; legacy data-theme values are removed
     before CSS can diverge from the shadcn preset. */
  try {
    var stored = localStorage.getItem('juno33-theme');
    var systemDark =
      window.matchMedia &&
      window.matchMedia('(prefers-color-scheme: dark)').matches;
    var dark = stored ? stored === 'dark' : systemDark;
    if (dark) document.documentElement.classList.add('dark');
    else document.documentElement.classList.remove('dark');
  } catch (e) {}

  try {
    document.documentElement.removeAttribute('data-theme');
    localStorage.removeItem('juno33-palette');
  } catch (e) {}
})();
