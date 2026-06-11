(function () {
  /* First-paint theme + palette resolve. Runs synchronously before React
     hydration so users never see a Juno-flash before Neptune kicks in
     (or a light-flash before dark mode kicks in). Reads from localStorage
     fast paths; remote sync from user_settings happens later in React. */
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
    var palette = localStorage.getItem('juno33-palette');
    var alts = ['neptune', 'apollo', 'mars', 'diana', 'vulcan', 'minerva'];
    if (alts.indexOf(palette) !== -1) {
      document.documentElement.setAttribute('data-theme', palette);
    }
    /* juno or unset = no data-theme attribute (matches @theme block in index.css). */
  } catch (e) {}
})();
