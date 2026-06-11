// Force-kill stale service workers on deploy — version bump triggers reload
// Guard: only reload ONCE per session to prevent infinite loops
(function(){
  var APP_VERSION = "2.1.3";
  var stored = localStorage.getItem("app_version");
  if (stored !== APP_VERSION && "serviceWorker" in navigator) {
    // Prevent infinite reload: if we already tried this session, stop
    if (sessionStorage.getItem("sw_reload_guard") === APP_VERSION) return;
    sessionStorage.setItem("sw_reload_guard", APP_VERSION);

    localStorage.setItem("app_version", APP_VERSION);
    navigator.serviceWorker.getRegistrations().then(function(regs) {
      var hadSW = regs.length > 0;
      Promise.all(regs.map(function(r) { return r.unregister(); })).then(function() {
        if (hadSW && typeof caches !== "undefined") {
          caches.keys().then(function(names) {
            Promise.all(names.map(function(n) { return caches.delete(n); })).then(function() {
              location.reload();
            });
          });
        } else if (hadSW) {
          location.reload();
        }
      });
    });
  }
})();
