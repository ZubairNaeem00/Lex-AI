import { useSyncExternalStore } from 'react';

/* Bookmarked precedent cases, kept in this browser so they survive reloads and
   stay available offline. The slider, the sidebar count and the saved-cases
   view all read the same snapshot through useSyncExternalStore. */

const STORAGE_KEY = 'lexai.saved_cases';
const listeners = new Set();

function read() {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
    return Array.isArray(raw) ? raw : [];
  } catch {
    return [];
  }
}

let snapshot = read();

function emit() {
  snapshot = read();
  listeners.forEach((listener) => listener());
}

function write(next) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  emit();
}

export function subscribeSavedCases(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getSavedCases() {
  return snapshot;
}

export function useSavedCases() {
  return useSyncExternalStore(subscribeSavedCases, getSavedCases);
}

export function isSaved(caseId) {
  return snapshot.some((item) => item.case_id === caseId);
}

export function useIsSaved(caseId) {
  const saved = useSavedCases();
  return saved.some((item) => item.case_id === caseId);
}

export function toggleSavedCase(record) {
  if (!record || record.case_id == null) return;
  if (isSaved(record.case_id)) {
    write(snapshot.filter((item) => item.case_id !== record.case_id));
  } else {
    write([record, ...snapshot]);
  }
}

export function removeSavedCase(caseId) {
  write(snapshot.filter((item) => item.case_id !== caseId));
}

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.key === STORAGE_KEY) emit();
  });
}
