/**
 * Минимальный pub-sub для toast-сообщений.
 * Компонент Toast подписывается, остальной код вызывает showToast(msg).
 */
const subscribers = new Set();

export function showToast(msg, durationMs = 2200) {
  subscribers.forEach((fn) => fn(msg, durationMs));
}

export function subscribe(fn) {
  subscribers.add(fn);
  return () => subscribers.delete(fn);
}
