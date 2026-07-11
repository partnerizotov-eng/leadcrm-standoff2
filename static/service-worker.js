// Service Worker for Web Push. Требует, чтобы сайт был на HTTPS
// (или localhost для разработки) — это ограничение самого браузера,
// не проекта.
self.addEventListener('push', function (event) {
  let data = { title: 'LeadCRM', body: '', url: '/' };
  try { data = event.data.json(); } catch (e) {}
  event.waitUntil(
    self.registration.showNotification(data.title || 'LeadCRM', {
      body: data.body || '',
      icon: '/static/icons/icon-192.png',
      data: { url: data.url || '/' },
    })
  );
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data.url || '/'));
});
