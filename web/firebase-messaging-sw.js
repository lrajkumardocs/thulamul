importScripts("https://www.gstatic.com/firebasejs/10.13.2/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/10.13.2/firebase-messaging-compat.js");

firebase.initializeApp({
  apiKey: "AIzaSyB3aUM0tQKByUaUg4jMGpHFDuVokkjFXg8",
  authDomain: "thulamul.firebaseapp.com",
  projectId: "thulamul",
  storageBucket: "thulamul.firebasestorage.app",
  messagingSenderId: "1075780759307",
  appId: "1:1075780759307:web:d10b25f39a1b54bc96fc0e",
});

const messaging = firebase.messaging();

messaging.onBackgroundMessage((payload) => {
  const d = payload.data || {};
  self.registration.showNotification(d.title || "துலாமுள்", {
    body: d.body || "",
    icon: "./icon.svg",
    badge: "./icon.svg",
    tag: d.tag || "thulamul",
    data: { url: d.url || "./" },
  });
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "./";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const c of list) {
        if (c.url.includes("/thulamul/") && "focus" in c) {
          c.navigate(url);
          return c.focus();
        }
      }
      return clients.openWindow(url);
    })
  );
});
