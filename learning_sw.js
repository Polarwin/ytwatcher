'use strict';
const ROOT = new URL('./', self.location.href).href;
const CACHE = 'ytwatcher-lesson:' + ROOT + ':v8';
const SHELL = ['index.html', 'learning_page.css', 'learning_page.js', 'learning_i18n.js', 'learning_share_ui.js', 'pack.json', 'manifest.webmanifest', 'offline-files.json', 'subtitles.vtt'];
self.addEventListener('install', event => event.waitUntil((async () => {
  const cache = await caches.open(CACHE);
  await cache.addAll(SHELL.map(file => new Request(new URL(file, ROOT), {cache: 'reload'})));
  // Install a complete new shell before switching workers, carrying saved media
  // forward so a UI upgrade does not require downloading the clip again.
  for (const name of await caches.keys()) {
    if (name === CACHE || !name.startsWith('ytwatcher-lesson:' + ROOT + ':')) continue;
    const previous = await caches.open(name);
    for (const request of await previous.keys()) {
      if (/\/media\.(mp4|m4a)$/.test(new URL(request.url).pathname)) {
        const response = await previous.match(request);
        if (response?.status === 200) await cache.put(request, response);
      }
    }
  }
  await self.skipWaiting();
})()));
self.addEventListener('activate', event => event.waitUntil((async () => {
  await self.clients.claim();
  for (const name of await caches.keys()) {
    if (name !== CACHE && name.startsWith('ytwatcher-lesson:' + ROOT + ':')) await caches.delete(name);
  }
})()));
self.addEventListener('fetch', event => {
  const req = event.request, url = new URL(req.url);
  if (!['GET', 'HEAD'].includes(req.method) || !url.href.startsWith(ROOT)) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const target = req.mode === 'navigate' ? new URL('index.html', ROOT).href : req;
    const saved = await cache.match(target, {ignoreSearch: true, ignoreMethod: true});
    if (saved) {
      const range = req.headers.get('Range');
      if (range) {
        const blob = await saved.blob(), match = /^bytes=(\d*)-(\d*)$/.exec(range);
        if (!match || !match[1] && !match[2]) return new Response(null, {status: 416, headers: {'Content-Range': 'bytes */' + blob.size}});
        const start = match[1] ? Number(match[1]) : Math.max(0, blob.size - Number(match[2]));
        const end = match[1] && match[2] ? Math.min(Number(match[2]), blob.size - 1) : blob.size - 1;
        if (start >= blob.size || start > end) return new Response(null, {status: 416, headers: {'Content-Range': 'bytes */' + blob.size}});
        return new Response(req.method === 'HEAD' ? null : blob.slice(start, end + 1), {status: 206, headers: {
          'Content-Type': saved.headers.get('Content-Type') || 'application/octet-stream',
          'Content-Length': String(end - start + 1), 'Content-Range': `bytes ${start}-${end}/${blob.size}`, 'Accept-Ranges': 'bytes'
        }});
      }
      if (req.method === 'HEAD') return new Response(null, {headers: saved.headers});
      return saved;
    }
    try {
      const response = await fetch(req);
      if (response.ok && req.method === 'GET' && !req.headers.has('Range') && response.status === 200) await cache.put(req, response.clone());
      return response;
    } catch (error) { return new Response('This file has not been saved offline yet. Connect and choose Save offline.', {status: 503}); }
  })());
});
