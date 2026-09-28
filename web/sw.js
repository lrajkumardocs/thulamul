// துலாமுள் — service worker: shell cache + offline
//
// V-ஐ ஒவ்வொரு வெளியீட்டிலும் மாற்ற வேண்டும். மாற்றாவிட்டால் ஏற்கெனவே
// நிறுவியவர்களுக்குப் பழைய பக்கமே காட்டப்படும் — புதுப்பிப்பு சேராது.
const V = 'thulamul-2026-09-28';
const SHELL = ['./', './index.html', './manifest.json', './icon-192.png', './icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== V).map(k => caches.delete(k)))
  ).then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // ── பக்கமே (index.html / './') : நெட்வொர்க் முதலில் ──
  // இல்லையெனில் ஆப்பை நிறுவியவர்களுக்குப் புதிய பதிப்பே சேராது.
  if (req.mode === 'navigate' ||
      url.pathname.endsWith('/') || url.pathname.endsWith('/index.html')) {
    e.respondWith(
      fetch(req).then(r => {
        if (r.ok && url.origin === location.origin) {
          const c = r.clone(); caches.open(V).then(x => x.put(req, c));
        }
        return r;
      }).catch(() => caches.match(req).then(hit => hit || caches.match('./index.html')))
    );
    return;
  }

  // ── தரவு: நெட்வொர்க் முதலில், இல்லையெனில் cache ──
  if (url.pathname.includes('/data/') || url.pathname.endsWith('.json')) {
    e.respondWith(
      fetch(req).then(r => { const c = r.clone(); caches.open(V).then(x => x.put(req, c)); return r; })
        .catch(() => caches.match(req))
    );
    return;
  }

  // ── மற்றவை (படம், எழுத்துரு): cache முதலில் ──
  e.respondWith(
    caches.match(req).then(hit => hit || fetch(req).then(r => {
      if (r.ok && url.origin === location.origin) { const c = r.clone(); caches.open(V).then(x => x.put(req, c)); }
      return r;
    }).catch(() => caches.match('./index.html')))
  );
});
