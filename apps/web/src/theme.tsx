import { useEffect, useState } from 'react';

type ThemePreference = 'system' | 'light' | 'dark';
const storageKey = 'astroprak.theme';
const normalize = (value: string | null): ThemePreference =>
  value === 'light' || value === 'dark' ? value : 'system';
let memoryPreference: ThemePreference = 'system';

function readPreference(): ThemePreference {
  try { memoryPreference = normalize(localStorage.getItem(storageKey)); }
  catch { /* Retain the current tab's choice when storage is unavailable. */ }
  return memoryPreference;
}

// Own state keeps theme changes independent of the session and mounted task.
export function ThemeSelect() {
  const [preference, setPreference] = useState<ThemePreference>(readPreference);

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const apply = () => {
      document.documentElement.dataset.theme = preference === 'system'
        ? (media.matches ? 'dark' : 'light') : preference;
    };
    apply();
    media.addEventListener('change', apply);
    return () => media.removeEventListener('change', apply);
  }, [preference]);

  useEffect(() => {
    const sync = (event: StorageEvent) => {
      if (event.key !== storageKey && event.key !== null) return;
      try { if (event.storageArea !== localStorage) return; } catch { return; }
      memoryPreference = normalize(event.newValue);
      setPreference(memoryPreference);
    };
    window.addEventListener('storage', sync);
    return () => window.removeEventListener('storage', sync);
  }, []);

  return (
    <label className="theme-select">
      Тема
      <select aria-label="Тема" value={preference} onChange={(event) => {
        const next = normalize(event.target.value);
        memoryPreference = next;
        setPreference(next);
        try { localStorage.setItem(storageKey, next); } catch { /* In-memory choice still works. */ }
      }}>
        <option value="system">Системная</option>
        <option value="light">Светлая</option>
        <option value="dark">Тёмная</option>
      </select>
    </label>
  );
}
