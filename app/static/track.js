/* AdPulse first-party tracking snippet.
 * <script src="https://YOUR-ADPULSE/t.js" data-client="client-slug" async></script>
 *
 * Nothing is sent until the visitor consents. Wire it to your consent banner / CMP:
 *   adpulse.consent(true)                     // after opt-in (e.g. in your CMP's callback)
 *   adpulse.track('add_to_cart', {value: 59})
 *   adpulse.track('purchase', {value: 129.90})
 *   adpulse.identify({email, first_name, postcode, consent: true})   // on a form with an explicit marketing opt-in box
 * Time on page is measured automatically (visible time only) and sent when the visitor leaves.
 * Set data-consent="granted" only where your legal basis allows tracking without opt-in.
 */
(function () {
  var s = document.currentScript || document.querySelector('script[data-client]');
  var client = s && s.getAttribute('data-client');
  var ENDPOINT = '__ENDPOINT__';
  var KEY = 'adpulse_id', CKEY = 'adpulse_consent', UKEY = 'adpulse_utm';
  var q = [], granted = false;

  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }
  function anon() {
    var id = store(KEY);
    if (!id) { id = (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2) + Date.now()); store(KEY, id); }
    return id;
  }
  function utm() {
    var p = new URLSearchParams(location.search), u = {};
    if (p.get('utm_source') || p.get('gclid') || p.get('fbclid') || p.get('ttclid')) {
      u.s = p.get('utm_source') || (p.get('gclid') ? 'google' : p.get('fbclid') ? 'facebook' : 'tiktok');
      u.m = p.get('utm_medium') || (p.get('gclid') || p.get('ttclid') ? 'cpc' : p.get('fbclid') ? 'paid' : '');
      u.cp = p.get('utm_campaign') || '';
      store(UKEY, JSON.stringify(u));
      return u;
    }
    var r = document.referrer;
    if (r && r.indexOf(location.hostname) === -1) {
      var h = new URL(r).hostname;
      if (/google\.|bing\.|duckduckgo\.|yahoo\./.test(h)) return { s: h.split('.').slice(-2, -1)[0], m: 'organic' };
      if (/facebook|instagram|t\.co|linkedin|tiktok|pinterest|reddit/.test(h)) return { s: h.replace('www.', '').split('.')[0], m: 'social' };
      return { s: h, m: 'referral' };
    }
    return {};
  }
  function send(ev, props) {
    var body = Object.assign({ c: client, a: anon(), e: ev, u: location.pathname }, props || {});
    var data = JSON.stringify(body);
    if (navigator.sendBeacon) navigator.sendBeacon(ENDPOINT, new Blob([data], { type: 'text/plain' }));
    else fetch(ENDPOINT, { method: 'POST', body: data, keepalive: true });
  }
  function enqueue(ev, props) { granted ? send(ev, props) : q.push([ev, props]); }

  var api = {
    consent: function (yes) {
      granted = !!yes; store(CKEY, yes ? '1' : '0');
      if (granted) { while (q.length) { var x = q.shift(); send(x[0], x[1]); } } else { q = []; }
    },
    track: function (ev, p) { p = p || {}; enqueue(ev, { v: p.value || 0 }); },
    identify: function (p) { enqueue('identify', { p: p || {} }); }
  };
  window.adpulse = api;

  // Engaged time on page: counts only while the tab is visible; each time the tab is hidden or closed
  // the time accrued since the last report is sent (the dashboard adds them up per page view).
  var shownAt = document.visibilityState === 'visible' ? Date.now() : 0, engaged = 0;
  function pause() { if (shownAt) { engaged += Date.now() - shownAt; shownAt = 0; } }
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') shownAt = Date.now();
    else { pause(); leave(); }
  });
  window.addEventListener('pagehide', function () { pause(); leave(); });
  function leave() {
    if (!granted || engaged < 1000) return;
    send('page_leave', { d: Math.round(engaged / 1000) });
    engaged = 0;
  }

  var first = utm();
  var ev = /pricing|plans/.test(location.pathname) ? 'pricing_view' : /product|\/p\//.test(location.pathname) ? 'product_view' : 'page_view';
  enqueue(ev, first);
  if (s && s.getAttribute('data-consent') === 'granted') api.consent(true);
  else if (store(CKEY) === '1') api.consent(true);
})();
