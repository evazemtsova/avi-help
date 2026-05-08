import { useCallback, useSyncExternalStore } from "react";

/**
 * SSR-safe matchMedia hook через useSyncExternalStore.
 * Получаем актуальное значение без промежуточного state.
 */
export function useMediaQuery(query) {
  const subscribe = useCallback(
    (cb) => {
      if (typeof window === "undefined" || !window.matchMedia) return () => {};
      const mq = window.matchMedia(query);
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    },
    [query]
  );
  const getSnapshot = useCallback(
    () =>
      typeof window !== "undefined" && window.matchMedia
        ? window.matchMedia(query).matches
        : false,
    [query]
  );
  // Server snapshot — false (default mobile-first ветка стилей).
  return useSyncExternalStore(subscribe, getSnapshot, () => false);
}
