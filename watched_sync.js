// Persist the latest local intent per video until the server acknowledges it.
var plWatchedPendingKey = 'ytwatcher:watched-pending-v1';
var plWatchedSyncBusy = false;
var plWatchedSyncTask = null;
function plWatchedPending() {
  try {
    var data = JSON.parse(localStorage.getItem(plWatchedPendingKey) || '{}');
    return data && typeof data === 'object' && !Array.isArray(data) ? data : {};
  } catch (e) { return {}; }
}
function plWatchedOverlay(ids) {
  var pending = plWatchedPending();
  Object.keys(pending).forEach(function (id) {
    if (pending[id].watched) ids.add(id); else ids.delete(id);
  });
  return ids;
}
function plWatchedStatus() {
  var count = Object.keys(plWatchedPending()).length;
  if (watchStatus) watchStatus.textContent = count ?
    count + ' watched change' + (count === 1 ? '' : 's') + ' saved on this device — waiting to sync' : '';
}
function plWatchedApplyRemote(data) {
  var next = plWatchedOverlay(new Set(data.ids || []));
  var changed = next.size !== watched.size || Array.from(next).some(function (id) { return !watched.has(id); });
  watched = next;
  save(watched);
  plCacheExpirySync(data);
  if (changed && typeof applyAll === 'function' && applyFns) applyAll();
  plWatchedStatus();
}
function plWatchedFlush() {
  if (!plWatchedSyncTask) {
    plWatchedSyncTask = plWatchedSend().finally(function () { plWatchedSyncTask = null; });
  }
  return plWatchedSyncTask;
}
async function plWatchedSend() {
  if (plWatchedSyncBusy) return;
  plWatchedSyncBusy = true;
  async function send() {
    var ids = Object.keys(plWatchedPending());
    for (var id of ids) {
      var change = plWatchedPending()[id];
      if (!change) continue;
      var controller = new AbortController();
      var timer = setTimeout(function () { controller.abort(); }, 10000);
      try {
        var response = await fetch(API + '/watched', {
          method: 'POST', headers: {'Content-Type': 'text/plain'},
          body: JSON.stringify({id: id, watched: change.watched, marked_at: change.marked_at}),
          signal: controller.signal
        });
        if (!response.ok) throw new Error('HTTP ' + response.status);
        var result = await response.json();
        var pending = plWatchedPending();
        // An older request must never discard a newer toggle of this video.
        if (pending[id] && pending[id].token === change.token) {
          delete pending[id];
          localStorage.setItem(plWatchedPendingKey, JSON.stringify(pending));
          plCacheExpiryMark(id, change.watched, result.marked_at);
        }
      } catch (e) { break; } // Server unreachable: retain the durable queue.
      finally { clearTimeout(timer); }
    }
  }
  try {
    // Serialize tabs where Web Locks are available. Replays are otherwise
    // idempotent because every retry carries the original watched timestamp.
    if (navigator.locks) await navigator.locks.request('ytwatcher-watched-sync', send);
    else await send();
  } finally { plWatchedSyncBusy = false; plWatchedStatus(); }
}
function plWatchedQueueChanges(changes) {
  var pending = plWatchedPending();
  var stamp = Date.now() / 1000;
  changes.forEach(function (change) {
    pending[change.id] = {watched: change.watched, marked_at: stamp, token: stamp + ':' + Math.random()};
  });
  try {
    localStorage.setItem(plWatchedPendingKey, JSON.stringify(pending));
  } catch (e) {
    watchStatus.textContent = 'Watched change could not be saved on this device.';
    return false;
  }
  plCacheExpiryMarkMany(changes, stamp);
  plWatchedStatus();
  return true;
}
function report(id, isWatched) {
  if (!plWatchedQueueChanges([{id: id, watched: isWatched}])) {
    if (isWatched) watched.delete(id); else watched.add(id);
    save(watched); applyAll();
    return;
  }
  plWatchedFlush();
}
watched = plWatchedOverlay(watched);

document.getElementById('watch-old').addEventListener('click', function () {
  var protectedIds = new Set(), candidates = new Set();
  var cutoff = Date.now() / 1000 - 2 * 86400;
  var entries = document.querySelectorAll('#video-sections li[data-id]');
  entries.forEach(function (li) {
    if (li.dataset.keepWatched === 'true') protectedIds.add(li.dataset.id);
  });
  // Include folded sections and old hidden rows; ignore duplicate Latest rows.
  entries.forEach(function (li) {
    var age = Number(li.dataset.added), id = li.dataset.id;
    if (li.dataset.added && Number.isFinite(age) && age < cutoff &&
        !protectedIds.has(id)) candidates.add(id);
  });
  var status = document.getElementById('watch-old-status');
  var changes = Array.from(candidates).filter(function (id) { return !watched.has(id); })
    .map(function (id) { return {id: id, watched: true}; });
  var oldPlaylist = pl.slice(), current = plIndex >= 0 ? pl[plIndex] : null;
  var remaining = pl.filter(function (item) { return !candidates.has(plItemId(item)); });
  var removed = pl.length - remaining.length;
  if (!changes.length && !removed) { status.textContent = 'No eligible unwatched videos older than 2 days.'; return; }
  if (!window.confirm('Mark ' + changes.length + ' videos older than 2 days as watched and remove ' + removed + ' playlist items? Categories that keep watched files are excluded.')) return;
  if (changes.length && !plWatchedQueueChanges(changes)) return;
  candidates.forEach(function (id) { watched.add(id); });
  save(watched);
  var next = null;
  if (current && !remaining.includes(current)) {
    next = oldPlaylist.slice(plIndex + 1).find(function (item) { return remaining.includes(item); });
    if (!next && plRepeat.checked) next = remaining[0];
    plVideo.pause();
    if (!next) plPlayer.hidden = true;
  }
  pl = remaining;
  plIndex = current ? pl.indexOf(current) : -1;
  plSave();
  if (next) plPlayAt(pl.indexOf(next));
  else plSavePos();
  applyAll();
  status.textContent = changes.length + ' videos marked watched; ' + removed + ' removed from playlist.';
  plWatchedFlush();
});
