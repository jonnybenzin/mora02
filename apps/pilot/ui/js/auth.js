/* ═══════════════════════════════════════════════════════════════
   MORA02 PILOT — Auth stage 1 (shared token)
   ═══════════════════════════════════════════════════════════════
   Loaded before every other script. Owns API_BASE and wraps
   window.fetch so that every call to the Pilot API carries the
   token from localStorage. On the first 401 the token is asked
   for once, stored, and the request is retried. No login, no
   users - that is stage 3.
   ═══════════════════════════════════════════════════════════════ */

const API_BASE = 'http://mora02.local:8098';

(function () {
  var KEY = 'pilot_token';
  var nativeFetch = window.fetch.bind(window);

  function readToken() {
    try { return localStorage.getItem(KEY) || ''; } catch (e) { return ''; }
  }
  function storeToken(t) {
    try { localStorage.setItem(KEY, t); } catch (e) {}
  }
  function forgetToken() {
    try { localStorage.removeItem(KEY); } catch (e) {}
  }
  function askToken(reason) {
    var t = window.prompt((reason || 'Pilot token required') +
      '\n\nMORA02_PILOT_TOKEN from docker/.env on the workstation:');
    if (t && t.trim()) { storeToken(t.trim()); return t.trim(); }
    return '';
  }
  function isPilot(url) {
    var u = (typeof url === 'string') ? url : (url && url.url) || '';
    return u.indexOf(API_BASE) === 0;
  }

  window.fetch = async function (url, opts) {
    if (!isPilot(url)) return nativeFetch(url, opts);
    opts = opts || {};
    var headers = new Headers(opts.headers || {});
    var token = readToken();
    if (!token) token = askToken('Pilot token required');
    if (token) headers.set('Authorization', 'Bearer ' + token);
    var resp = await nativeFetch(url, Object.assign({}, opts, { headers: headers }));
    if (resp.status === 401) {
      forgetToken();
      var again = askToken('Token rejected');
      if (again) {
        headers.set('Authorization', 'Bearer ' + again);
        resp = await nativeFetch(url, Object.assign({}, opts, { headers: headers }));
      }
    }
    return resp;
  };

  /* for the settings page: forget the stored token */
  window.pilotForgetToken = forgetToken;
})();
