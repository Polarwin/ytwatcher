// Embedded in the library page. Only the playlist media cache is managed here.
var plCacheExpiryKey = 'ytwatcher:cache-expiry-v1';
var plCacheExpiryGrace = 90 * 60 * 1000;
var plCacheExpiryBusy = false;
var plCacheExpiryGeneration = 0;
function plCacheExpiryRead() {
  try {
    var value = JSON.parse(localStorage.getItem(plCacheExpiryKey) || '{}');
    return {marks: value.marks || {}, assets: value.assets || {}};
  } catch (e) { return {marks: {}, assets: {}}; }
}
function plCacheExpiryWrite(value) {
  try { localStorage.setItem(plCacheExpiryKey, JSON.stringify(value)); } catch (e) {}
}
function plCacheExpiryPath(href) {
  try { return new URL(href, location.href).pathname; } catch (e) { return ''; }
}
function plCacheExpiryRemember(state) {
  function remember(id, href, subs) {
    if (!id || !href) return;
    state.assets[plCacheExpiryPath(href)] = id;
    try {
      var tracks = typeof subs === 'string' ? JSON.parse(subs || '{}') : subs;
      Object.values(tracks || {}).forEach(function (url) {
        state.assets[plCacheExpiryPath(url)] = id;
        state.assets[plCacheExpiryPath(url.replace(/\.vtt(\?.*)?$/, '.dict.json'))] = id;
      });
    } catch (e) {}
  }
  document.querySelectorAll('#video-sections li[data-id]').forEach(function (li) {
    var link = li.querySelector('a');
    if (link) remember(li.dataset.id, link.getAttribute('href'), li.dataset.subs);
  });
  (pl || []).forEach(function (item) {
    if (!item.static) remember(plItemId(item), item.href, item.subs);
  });
}
function plCacheExpiryId(path, state) {
  if (state.assets[path]) return state.assets[path];
  try {
    var match = decodeURIComponent(path).match(/\[([A-Za-z0-9_-]{11})\]/);
    return match && match[1];
  } catch (e) { return null; }
}
function plCacheExpirySync(data) {
  if (!data.marks) return; // Compatibility with an older server.
  var state = plCacheExpiryRead(), marks = {};
  Object.keys(data.marks).forEach(function (id) {
    var stamp = Number(data.marks[id]);
    if (Number.isFinite(stamp) && stamp >= 0) marks[id] = stamp * 1000;
  });
  // The server prunes path-based IDs after deleting their files. Retain already
  // due local marks for those IDs until their device cache has been cleaned.
  Object.keys(state.marks).forEach(function (id) {
    if (/^m_?[a-f0-9]{10}$/.test(id) && !(id in marks) &&
        Date.now() - state.marks[id] >= plCacheExpiryGrace) marks[id] = state.marks[id];
  });
  state.marks = marks;
  plCacheExpiryRemember(state);
  plCacheExpiryWrite(state);
}
function plCacheExpiryMark(id, isWatched, timestamp) {
  plCacheExpiryGeneration++;
  var state = plCacheExpiryRead();
  plCacheExpiryRemember(state);
  if (isWatched) state.marks[id] = Number.isFinite(timestamp) ? timestamp * 1000 : Date.now();
  else delete state.marks[id];
  plCacheExpiryWrite(state);
}
async function plCacheExpirySweep() {
  if (!('caches' in window)) return;
  var state = plCacheExpiryRead();
  plCacheExpiryRemember(state);
  plCacheExpiryWrite(state);
  var cache = await caches.open('ytwatcher-media-v1');
  var requests = await cache.keys();
  var playing = plVideo && !plVideo.paused ? plCacheExpiryId(plCacheExpiryPath(plVideo.currentSrc), state) : null;
  for (var request of requests) {
    var path = plCacheExpiryPath(request.url), id = plCacheExpiryId(path, state);
    // Re-read marks so an unmark in another tab cancels pending cleanup.
    var latest = plCacheExpiryRead();
    if (!id || id === playing || !(id in latest.marks) ||
        Date.now() - latest.marks[id] < plCacheExpiryGrace) continue;
    await cache.delete(request);
  }
}
async function plCacheExpiryRefresh() {
  if (plCacheExpiryBusy || document.hidden) return;
  plCacheExpiryBusy = true;
  try {
    try {
      var generation = plCacheExpiryGeneration;
      var controller = new AbortController();
      var timeout = setTimeout(function () { controller.abort(); }, 10000);
      try {
        var response = await fetch(API + '/watched', {cache: 'no-store', signal: controller.signal});
        var data = response.ok ? await response.json() : null;
        if (data && generation === plCacheExpiryGeneration) plCacheExpirySync(data);
      } finally { clearTimeout(timeout); }
    } catch (e) { /* Offline: use previously confirmed watched timestamps. */ }
    await plCacheExpirySweep();
  } catch (e) { console.warn('Offline cache cleanup postponed:', e); }
  finally { plCacheExpiryBusy = false; }
}
setInterval(plCacheExpiryRefresh, 60000);
window.addEventListener('pageshow', plCacheExpiryRefresh);
window.addEventListener('online', plCacheExpiryRefresh);
document.addEventListener('visibilitychange', function () {
  if (!document.hidden) plCacheExpiryRefresh();
});
