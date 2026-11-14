const STORAGE_KEY = 'lexai.theme';

export const THEMES = [
  { key: 'light', label: 'Light', note: 'Daylight chambers' },
  { key: 'dark', label: 'Dark', note: 'Late-night reading' },
];

export function getTheme() {
  const saved = localStorage.getItem(STORAGE_KEY);
  return THEMES.some((theme) => theme.key === saved) ? saved : 'light';
}

export function setTheme(theme) {
  localStorage.setItem(STORAGE_KEY, theme);
  document.documentElement.dataset.theme = theme;
  return theme;
}

/* Runs before the first paint so a reload never flashes the other palette. */
setTheme(getTheme());