import { useSyncExternalStore } from "react";

/**
 * Глобальное состояние поповера-кластера источников.
 * Один кластер = группа sources, привязанных к месту в тексте.
 * SourceCluster зовёт openCluster(id, sources, anchorRect) при клике.
 * <SourcePopover /> подписан, рендерит список ссылок в portal.
 */

let state = null; // { clusterId, sources, anchorRect } | null
const subs = new Set();

function emit() {
  subs.forEach((fn) => fn());
}

export function openCluster(clusterId, sources, anchorRect) {
  state = { clusterId, sources, anchorRect };
  emit();
}

export function closeCluster() {
  if (state === null) return;
  state = null;
  emit();
}

function subscribe(fn) {
  subs.add(fn);
  return () => subs.delete(fn);
}

function getSnapshot() {
  return state;
}

export function useActiveCluster() {
  return useSyncExternalStore(subscribe, getSnapshot, () => null);
}

export function useIsClusterActive(clusterId) {
  const s = useActiveCluster();
  return s?.clusterId === clusterId;
}
