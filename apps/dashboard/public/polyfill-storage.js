// Polyfill localStorage for Mobile Safari private browsing / restricted storage
// where localStorage is null. Provides in-memory fallback so the app doesn't crash.
(function(){
  try { if (window.localStorage) return; } catch(e) { /* throws in some contexts */ }
  var mem = {};
  Object.defineProperty(window, 'localStorage', {
    value: {
      getItem: function(k) { return mem.hasOwnProperty(k) ? mem[k] : null; },
      setItem: function(k, v) { mem[k] = String(v); },
      removeItem: function(k) { delete mem[k]; },
      clear: function() { mem = {}; },
      get length() { return Object.keys(mem).length; },
      key: function(i) { return Object.keys(mem)[i] || null; }
    },
    writable: true,
    configurable: true
  });
})();
