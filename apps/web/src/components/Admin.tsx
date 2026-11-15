import React, { useState, useEffect, useMemo } from 'react';

interface TaskAdminInfo {
  id: string;
  valid: boolean;
  hidden: boolean;
  title?: string;
  category?: string;
  category_order?: number;
  has_generator: boolean;
  has_widget: boolean;
  error?: string;
}

interface UserSessionInfo {
  attempt_id: number;
  user_id: number;
  user_key: string;
  task_id: string;
  seed: number;
  answers: Record<string, any>;
  submitted: boolean;
  score?: number | null;
  grading?: Record<string, any> | null;
  submitted_at: string | null;
  created_at: string;
  events_count: number;
  duration_sec: number;
}

interface BackupFileInfo {
  filename: string;
  size_kb: number;
  modified_at: string;
}

interface BackupStatusInfo {
  interval_minutes: number;
  last_backup_at: string | null;
  last_backup_file: string | null;
  last_error: string | null;
  total_attempts: number;
  submitted_attempts: number;
  files: BackupFileInfo[];
}

type SessionRowOrGroup =
  | { kind: 'single'; session: UserSessionInfo }
  | { kind: 'short_group'; groupId: string; items: UserSessionInfo[] };

const PAGE_SIZE = 100;

export function AdminPanel({ onBack }: { onBack: () => void }) {
  const [token, setToken] = useState<string>(() => sessionStorage.getItem('admin_token') || '');
  const [inputToken, setInputToken] = useState('');
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [tab, setTab] = useState<'tasks' | 'sessions' | 'backups'>('tasks');

  const [tasks, setTasks] = useState<TaskAdminInfo[]>([]);

  // Пагинация, глобальный поиск и фильтрация сессий
  const [sessions, setSessions] = useState<UserSessionInfo[]>([]);
  const [totalSessions, setTotalSessions] = useState<number>(0);
  const [offset, setOffset] = useState<number>(0);
  const [searchInput, setSearchInput] = useState('');
  const [appliedQuery, setAppliedQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [excludeShortServer, setExcludeShortServer] = useState<boolean>(false);

  // Группировка и сворачивание коротких сессий (< 5 с)
  const [collapseShort, setCollapseShort] = useState<boolean>(true);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});

  const [selectedEvents, setSelectedEvents] = useState<any[] | null>(null);
  const [activeAttemptId, setActiveAttemptId] = useState<number | null>(null);

  // Резервные копии
  const [backupInfo, setBackupInfo] = useState<BackupStatusInfo | null>(null);
  const [restoreFile, setRestoreFile] = useState<File | null>(null);

  // Категории и drag-and-drop
  const [categoryOrder, setCategoryOrder] = useState<string[]>([]);
  const [draggedCatIndex, setDraggedCatIndex] = useState<number | null>(null);

  const [msg, setMsg] = useState<string | null>(null);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState<File | null>(null);

  async function checkAndLoad(testToken: string) {
    setBusy(true);
    setLoginError(null);
    try {
      const res = await fetch('/api/admin/tasks', { headers: { Authorization: `Bearer ${testToken}` } });
      if (res.status === 429) throw new Error('Превышен лимит попыток. IP заблокирован.');
      if (res.status === 401 || res.status === 403) throw new Error('Неверный токен администратора.');
      if (!res.ok) throw new Error(await res.text());

      const data = await res.json();
      setTasks(Array.isArray(data.tasks) ? data.tasks : []);
      setToken(testToken);
      sessionStorage.setItem('admin_token', testToken);
      setIsAuthenticated(true);
      void loadCategories();
    } catch (e: any) {
      setIsAuthenticated(false);
      setLoginError(e.message);
      sessionStorage.removeItem('admin_token');
    } finally {
      setBusy(false);
    }
  }

  async function loadCategories() {
    try {
      const res = await fetch('/api/categories');
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data.categories)) {
          setCategoryOrder(data.categories);
        }
      }
    } catch (e) {
      console.error(e);
    }
  }

  async function saveCategoryOrder(newOrder: string[]) {
    setCategoryOrder(newOrder);
    try {
      const res = await fetch('/api/admin/categories/order', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ categories: newOrder })
      });
      if (!res.ok) throw new Error(await res.text());
      setMsg('Порядок категорий успешно сохранён!');
    } catch (err: any) {
      setMsg(`Ошибка сохранения порядка: ${err.message}`);
    }
  }

  async function loadSessions(targetOffset = 0, append = false, queryOverride?: string) {
    setBusy(true);
    try {
      const qVal = queryOverride !== undefined ? queryOverride : appliedQuery;
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(targetOffset),
      });
      if (qVal.trim()) params.set('q', qVal.trim());
      if (statusFilter) params.set('status_filter', statusFilter);
      if (excludeShortServer) params.set('exclude_short', 'true');

      const res = await fetch(`/api/admin/sessions?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        const incoming: UserSessionInfo[] = Array.isArray(data.sessions) ? data.sessions : [];
        setTotalSessions(typeof data.total === 'number' ? data.total : incoming.length);
        if (append) {
          setSessions((prev) => {
            const seen = new Set(prev.map((x) => x.attempt_id));
            return [...prev, ...incoming.filter((x) => !seen.has(x.attempt_id))];
          });
        } else {
          setSessions(incoming);
          setOffset(targetOffset);
        }
      }
    } catch (e) {
      console.error(e);
    } finally {
      setBusy(false);
    }
  }

  async function loadBackups() {
    try {
      const res = await fetch('/api/admin/backups', {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setBackupInfo(data);
      }
    } catch (e) {
      console.error(e);
    }
  }

  async function triggerManualBackup() {
    setBusy(true);
    setMsg(null);
    try {
      const res = await fetch('/api/admin/backups/create', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Ошибка создания бэкапа');
      setMsg(data.message);
      if (data.state) setBackupInfo(data.state);
      else await loadBackups();
    } catch (e: any) {
      setMsg(`Ошибка бэкапа: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function downloadBackupFile(filename: string) {
    try {
      const res = await fetch(`/api/admin/backups/download/${encodeURIComponent(filename)}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) throw new Error('Не удалось скачать файл резервной копии');
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (e: any) {
      alert(e.message);
    }
  }

  async function handleRestoreBackup(e: React.FormEvent) {
    e.preventDefault();
    if (!restoreFile) return;
    const ok = window.confirm(
      `Восстановить и дополнить таблицу попыток и пользователей из файла «${restoreFile.name}»?`
    );
    if (!ok) return;

    setBusy(true);
    setMsg(null);
    const form = new FormData();
    form.append('file', restoreFile);
    try {
      const res = await fetch('/api/admin/backups/restore', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: form
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Ошибка восстановления');
      setMsg(data.message);
      setRestoreFile(null);
      await loadBackups();
      await loadSessions(0, false);
    } catch (err: any) {
      setMsg(`Ошибка восстановления: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function viewEvents(attemptId: number) {
    setActiveAttemptId(attemptId);
    setSelectedEvents(null);
    try {
      const res = await fetch(`/api/admin/sessions/${attemptId}/events`, { 
        headers: { Authorization: `Bearer ${token}` } 
      });
      if (res.ok) {
        const data = await res.json();
        setSelectedEvents(data.events || []);
      }
    } catch (e) {
      console.error(e);
    }
  }

  async function toggleTaskVisibility(taskId: string) {
    setBusy(true); setMsg(null);
    try {
      const res = await fetch(`/api/admin/tasks/${encodeURIComponent(taskId)}/toggle-visibility`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setMsg(data.message);
      await checkAndLoad(token);
    } catch (e: any) {
      setMsg(`Ошибка: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function updateTaskCategory(taskId: string, category: string, order = 100) {
    try {
      const res = await fetch(`/api/admin/tasks/${encodeURIComponent(taskId)}/category`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ category, category_order: order })
      });
      if (!res.ok) throw new Error(await res.text());
      setTasks((prev) => prev.map((t) => (t.id === taskId ? { ...t, category, category_order: order } : t)));
      setMsg(`Категория задачи "${taskId}" сохранена: "${category || 'Без категории'}"`);
    } catch (e: any) {
      setMsg(`Ошибка: ${e.message}`);
    }
  }

  async function deleteTask(taskId: string) {
    const ok = window.confirm(`Вы действительно хотите безвозвратно удалить задачу "${taskId}" с диска?`);
    if (!ok) return;

    setBusy(true); setMsg(null);
    try {
      const res = await fetch(`/api/admin/tasks/${encodeURIComponent(taskId)}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setMsg(data.message);
      await checkAndLoad(token);
    } catch (e: any) {
      setMsg(`Ошибка удаления: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function downloadDocsZip() {
    try {
      const res = await fetch('/api/admin/docs/export/zip', { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) throw new Error('Не удалось скачать документацию');
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'astrosite_docs_and_template.zip';
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (e: any) {
      alert(e.message);
    }
  }

  async function downloadAttemptJson(attemptId: number) {
    try {
      const res = await fetch(`/api/admin/sessions/${attemptId}/export/json`, { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) throw new Error('Не удалось скачать JSON');
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `attempt_${attemptId}.json`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (e: any) {
      alert(e.message);
    }
  }

  function buildExportQueryString(): string {
    const params = new URLSearchParams();
    if (appliedQuery.trim()) params.set('q', appliedQuery.trim());
    if (statusFilter) params.set('status_filter', statusFilter);
    if (excludeShortServer) params.set('exclude_short', 'true');
    const qs = params.toString();
    return qs ? `?${qs}` : '';
  }

  async function downloadAllCsv() {
    try {
      const res = await fetch(`/api/admin/sessions/export/csv${buildExportQueryString()}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) throw new Error('Не удалось скачать CSV');
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `astrosite_sessions_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (e: any) {
      alert(e.message);
    }
  }

  async function downloadAllEventsCsv() {
    try {
      const res = await fetch(`/api/admin/sessions/export/events-csv${buildExportQueryString()}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) throw new Error('Не удалось скачать лог действий CSV');
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `astrosite_events_log_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (e: any) {
      alert(e.message);
    }
  }

  async function downloadFullSessionsJson() {
    try {
      const res = await fetch(`/api/admin/sessions/export/full-json${buildExportQueryString()}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) throw new Error('Не удалось скачать полный JSON логов');
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `astrosite_all_sessions_with_logs_${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (e: any) {
      alert(e.message);
    }
  }

  useEffect(() => {
    if (token) {
      void checkAndLoad(token);
    }
  }, []);

  // Debounce серверного поиска по всем работам
  useEffect(() => {
    const timer = setTimeout(() => {
      setAppliedQuery(searchInput);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    if (isAuthenticated && tab === 'sessions') {
      void loadSessions(0, false);
      void loadBackups();
    }
    if (isAuthenticated && tab === 'backups') {
      void loadBackups();
    }
  }, [tab, isAuthenticated, appliedQuery, statusFilter, excludeShortServer]);

  function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    if (inputToken.trim()) void checkAndLoad(inputToken.trim());
  }

  async function handleRescan() {
    setBusy(true); setMsg(null);
    try {
      const res = await fetch('/api/admin/tasks/rescan', { method: 'POST', headers: { Authorization: `Bearer ${token}` } });
      const data = await res.json();
      setMsg(`Хранилище пересканировано. Активных задач: ${data.loaded}`);
      await checkAndLoad(token);
    } catch (e: any) {
      setMsg(`Ошибка: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function uploadZipFile(fileToUpload: File, overwrite = false) {
    setBusy(true); setMsg(null);
    const form = new FormData();
    form.append('file', fileToUpload);

    try {
      const url = `/api/admin/tasks/upload?overwrite=${overwrite ? 'true' : 'false'}`;
      const res = await fetch(url, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: form
      });

      const data = await res.json();
      if (res.status === 200 && data.status === 'conflict') {
        const confirmReplace = window.confirm(
          `Внимание!\nЗадача «${data.title}» (ID: ${data.task_id}) уже существует на сервере.\n\nЗаменить её?`
        );
        if (confirmReplace) {
          await uploadZipFile(fileToUpload, true);
        } else {
          setMsg('Загрузка отменена.');
        }
        return;
      }

      if (!res.ok) throw new Error(data.detail || 'Не удалось загрузить архив');

      setMsg(data.message);
      setFile(null);
      await checkAndLoad(token);
    } catch (e: any) {
      setMsg(`Ошибка загрузки: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    await uploadZipFile(file, false);
  }

  const allCategories = useMemo(() => {
    const set = new Set<string>(categoryOrder || []);
    (tasks || []).forEach((t) => {
      if (t && t.category && t.category.trim()) {
        set.add(t.category.trim());
      }
    });
    return Array.from(set).filter(Boolean);
  }, [categoryOrder, tasks]);

  const handleDrop = (targetIndex: number) => {
    if (draggedCatIndex === null || draggedCatIndex === targetIndex) return;
    const list = [...allCategories];
    const [removed] = list.splice(draggedCatIndex, 1);
    list.splice(targetIndex, 0, removed);
    setDraggedCatIndex(null);
    void saveCategoryOrder(list);
  };

  // Группировка подряд идущих коротких (< 5 с, несданных) сессий
  const groupedDisplayRows = useMemo<SessionRowOrGroup[]>(() => {
    if (!collapseShort) {
      return (sessions || []).map((s) => ({ kind: 'single', session: s }));
    }
    const out: SessionRowOrGroup[] = [];
    let buffer: UserSessionInfo[] = [];

    const flushBuffer = () => {
      if (buffer.length === 0) return;
      if (buffer.length === 1) {
        out.push({ kind: 'single', session: buffer[0] });
      } else {
        const groupId = `grp_${buffer[0].attempt_id}_${buffer[buffer.length - 1].attempt_id}`;
        out.push({ kind: 'short_group', groupId, items: [...buffer] });
      }
      buffer = [];
    };

    for (const s of sessions || []) {
      const isShortNoise = !s.submitted && (s.duration_sec || 0) < 5;
      if (isShortNoise) {
        buffer.push(s);
      } else {
        flushBuffer();
        out.push({ kind: 'single', session: s });
      }
    }
    flushBuffer();
    return out;
  }, [sessions, collapseShort]);

  const shortSessionsCountOnPage = useMemo(
    () => (sessions || []).filter((s) => !s.submitted && (s.duration_sec || 0) < 5).length,
    [sessions]
  );

  if (!isAuthenticated) {
    return (
      <div style={{ maxWidth: 420, margin: '60px auto', padding: 24, border: '1px solid #cbd5e0', borderRadius: 8, background: '#fff' }}>
        <h3 style={{ marginTop: 0 }}>Вход в панель управления</h3>
        <p style={{ fontSize: 13, color: '#666' }}>Панель защищена от перебора паролей (Rate Limit).</p>
        {loginError && <div style={{ padding: 10, background: '#fff5f5', color: '#c53030', borderRadius: 4, marginBottom: 12, fontSize: 14 }}>{loginError}</div>}
        <form onSubmit={handleLogin}>
          <input
            type="password"
            placeholder="Введите ADMIN_TOKEN"
            value={inputToken}
            onChange={(e) => setInputToken(e.target.value)}
            style={{ width: '100%', padding: '10px', boxSizing: 'border-box', marginBottom: 14, borderRadius: 4, border: '1px solid #ccc' }}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <button type="button" onClick={onBack} style={{ background: 'none', border: 'none', color: '#4a5568', cursor: 'pointer' }}>← В каталог</button>
            <button type="submit" disabled={busy} style={{ padding: '8px 18px', background: '#3182ce', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}>
              {busy ? 'Проверка...' : 'Войти'}
            </button>
          </div>
        </form>
      </div>
    );
  }

  function renderSessionRow(s: UserSessionInfo, isNested = false) {
    return (
      <tr
        key={s.attempt_id}
        style={{
          borderBottom: '1px solid #e2e8f0',
          background: isNested ? '#fcfdfe' : '#fff',
          opacity: !s.submitted && s.duration_sec < 5 ? 0.82 : 1
        }}
      >
        <td style={{ padding: 8, fontWeight: 600 }}>#{s.attempt_id}</td>
        <td style={{ padding: 8 }}>
          <code style={{ background: '#edf2f7', padding: '2px 6px', borderRadius: 4, fontSize: 12 }}>
            {s.user_key}
          </code>
        </td>
        <td style={{ padding: 8 }}>{s.task_id}</td>
        <td style={{ padding: 8 }}>
          <div>{s.duration_sec >= 5 ? `${s.duration_sec} с.` : '< 5 с.'}</div>
          <div style={{ fontSize: 11, color: '#718096' }}>{s.created_at}</div>
        </td>
        <td style={{ padding: 8 }}>
          {s.submitted ? (
            <div>
              <span style={{ 
                color: s.score !== null && s.score !== undefined ? (s.score >= 3.5 ? '#16a34a' : '#d97706') : '#2f855a', 
                fontWeight: 700 
              }}>
                ✓ Сдано {s.score !== null && s.score !== undefined ? `(${s.score} б.)` : ''}
              </span>
              {s.grading && s.grading.details && (
                <details style={{ marginTop: 4, fontSize: 11 }}>
                  <summary style={{ cursor: 'pointer', color: '#2563eb' }}>Протокол</summary>
                  <div style={{ background: '#f8fafc', padding: 6, borderRadius: 4, marginTop: 4, border: '1px solid #e2e8f0' }}>
                    {Object.entries(s.grading.details).map(([key, item]: [string, any]) => (
                      <div key={key} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, margin: '2px 0' }}>
                        <span style={{ fontWeight: 600 }}>{key}:</span>
                        <span style={{ color: item.ok ? '#16a34a' : '#dc2626' }}>
                          ввод: {item.user !== null && item.user !== undefined ? String(item.user) : '—'} (эталон: {String(item.truth)} ± {item.tol || 0}) ➔ {item.score} б.
                        </span>
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </div>
          ) : (
            <span style={{ color: '#d69e2e', fontWeight: 600 }}>В процессе</span>
          )}
        </td>
        <td style={{ padding: 8, fontFamily: 'monospace', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={s.answers ? JSON.stringify(s.answers) : ''}>
          {s.answers && Object.keys(s.answers).length > 0 ? JSON.stringify(s.answers) : '—'}
        </td>
        <td style={{ padding: 8 }}>
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              onClick={() => downloadAttemptJson(s.attempt_id)}
              style={{ padding: '3px 8px', background: '#edf2f7', border: '1px solid #cbd5e0', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
            >
              JSON
            </button>
            <button
              onClick={() => viewEvents(s.attempt_id)}
              style={{ padding: '3px 8px', background: activeAttemptId === s.attempt_id ? '#2b6cb0' : '#edf2f7', color: activeAttemptId === s.attempt_id ? '#fff' : '#000', border: '1px solid #cbd5e0', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
            >
              Лог ({s.events_count})
            </button>
          </div>
        </td>
      </tr>
    );
  }

  const hasPrevPage = offset > 0;
  const hasNextPage = offset + sessions.length < totalSessions;
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(totalSessions / PAGE_SIZE));

  return (
    <div style={{ maxWidth: 1280, margin: '0 auto', padding: 20 }}>
      <datalist id="category-presets">
        <option value="Архив ВсОШ / 9 класс" />
        <option value="Архив ВсОШ / 10 класс" />
        <option value="Архив ВсОШ / 11 класс" />
        <option value="Интерактивные практикумы и тренажёры" />
        <option value="Звёздная астрономия" />
        {allCategories.map((c) => (
          <option key={c} value={c} />
        ))}
      </datalist>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2>Администрирование Astrosite v2.0</h2>
        <button onClick={onBack} style={{ padding: '8px 16px', background: '#718096', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}>
          В каталог
        </button>
      </div>

      <div style={{ display: 'flex', gap: 10, borderBottom: '2px solid #e2e8f0', marginBottom: 20 }}>
        <button
          onClick={() => setTab('tasks')}
          style={{ padding: '10px 20px', border: 'none', background: tab === 'tasks' ? '#edf2f7' : 'none', fontWeight: tab === 'tasks' ? 700 : 400, borderBottom: tab === 'tasks' ? '3px solid #3182ce' : 'none', cursor: 'pointer' }}
        >
          Хранилище задач ({(tasks || []).length})
        </button>
        <button
          onClick={() => setTab('sessions')}
          style={{ padding: '10px 20px', border: 'none', background: tab === 'sessions' ? '#edf2f7' : 'none', fontWeight: tab === 'sessions' ? 700 : 400, borderBottom: tab === 'sessions' ? '3px solid #3182ce' : 'none', cursor: 'pointer' }}
        >
          Аналитика сессий ({totalSessions || (sessions || []).length})
        </button>
        <button
          onClick={() => setTab('backups')}
          style={{ padding: '10px 20px', border: 'none', background: tab === 'backups' ? '#edf2f7' : 'none', fontWeight: tab === 'backups' ? 700 : 400, borderBottom: tab === 'backups' ? '3px solid #3182ce' : 'none', cursor: 'pointer' }}
        >
          Резервные копии ({backupInfo?.files?.length ?? 0})
        </button>
      </div>

      {msg && <div style={{ padding: 12, background: '#ebf8ff', border: '1px solid #bee3f8', borderRadius: 4, marginBottom: 16 }}>{msg}</div>}

      {/* ВКЛАДКА 1: ЗАДАЧИ */}
      {tab === 'tasks' && (
        <>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
            <button onClick={handleRescan} disabled={busy} style={{ padding: '8px 16px', background: '#2f855a', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}>
              ⟳ Пересканировать хранилище
            </button>
            <button
              onClick={downloadDocsZip}
              style={{ padding: '8px 16px', background: '#2b6cb0', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontWeight: 600 }}
              title="Скачать все спецификации и готовую папку-шаблон _template"
            >
              📦 Скачать спецификации и шаблон (ZIP)
            </button>
          </div>

          <div style={{ background: '#f8fafc', padding: 16, borderRadius: 8, border: '1px solid #cbd5e0', marginBottom: 20 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <h4 style={{ margin: 0 }}>Порядок тем в каталоге (перетащите мышкой за карточку):</h4>
              <span style={{ fontSize: 12, color: '#718096' }}>Слева направо = сверху вниз на главной</span>
            </div>
            
            {allCategories.length === 0 ? (
              <p style={{ margin: 0, fontSize: 13, color: '#718096' }}>Категории пока не назначены. Введите название категории в таблице ниже.</p>
            ) : (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {allCategories.map((cat, idx) => (
                  <div
                    key={cat}
                    draggable
                    onDragStart={() => setDraggedCatIndex(idx)}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={() => handleDrop(idx)}
                    style={{
                      padding: '6px 12px',
                      background: '#fff',
                      border: '1px solid #cbd5e0',
                      borderRadius: 6,
                      cursor: 'grab',
                      userSelect: 'none',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                      boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
                      fontSize: 13
                    }}
                    title="Зажмите и перетащите в нужное место"
                  >
                    <span style={{ color: '#a0aec0', cursor: 'grab' }}>☰</span>
                    <span style={{ fontWeight: 600, color: '#2d3748' }}>{idx + 1}.</span>
                    <span>{cat}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div style={{ background: '#f7fafc', padding: 16, borderRadius: 8, border: '1px solid #e2e8f0', marginBottom: 24 }}>
            <h4 style={{ margin: '0 0 10px 0' }}>Загрузка пакета (.zip)</h4>
            <form onSubmit={handleUpload} style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
              <input type="file" accept=".zip" onChange={(e) => setFile(e.target.files?.[0] || null)} />
              <button type="submit" disabled={busy || !file} style={{ padding: '6px 14px', background: '#3182ce', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}>
                Загрузить на лету
              </button>
            </form>
          </div>

          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
            <thead>
              <tr style={{ background: '#edf2f7', borderBottom: '2px solid #cbd5e0' }}>
                <th style={{ padding: 10 }}>Task ID</th>
                <th style={{ padding: 10 }}>Название</th>
                <th style={{ padding: 10, width: 260 }}>Категория / Папка</th>
                <th style={{ padding: 10 }}>Тип</th>
                <th style={{ padding: 10 }}>Виджет</th>
                <th style={{ padding: 10 }}>Статус</th>
                <th style={{ padding: 10, textAlign: 'right' }}>Действия</th>
              </tr>
            </thead>
            <tbody>
              {(tasks || []).map((t) => (
                <tr key={t.id} style={{ borderBottom: '1px solid #e2e8f0', background: !t.valid ? '#fff5f5' : t.hidden ? '#fafafa' : '#fff' }}>
                  <td style={{ padding: 10, fontFamily: 'monospace', fontWeight: 600 }}>{t.id}</td>
                  <td style={{ padding: 10 }}>{t.title || '—'}</td>
                  <td style={{ padding: 10 }}>
                    <input
                      type="text"
                      list="category-presets"
                      defaultValue={t.category || ''}
                      placeholder="Напр. Архив ВсОШ"
                      onBlur={(e) => {
                        if (e.target.value !== (t.category || '')) {
                          void updateTaskCategory(t.id, e.target.value);
                        }
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
                      }}
                      style={{
                        width: '100%',
                        padding: '5px 8px',
                        fontSize: 12,
                        borderRadius: 4,
                        border: '1px solid #cbd5e0',
                        boxSizing: 'border-box'
                      }}
                      title="Нажмите Enter или кликните в сторону для сохранения"
                    />
                  </td>
                  <td style={{ padding: 10, fontSize: 12 }}>
                    {t.has_generator ? 'Практикум' : 'Справка'}
                  </td>
                  <td style={{ padding: 10, fontSize: 12 }}>{t.has_widget ? 'widget.html' : '—'}</td>
                  <td style={{ padding: 10 }}>
                    {!t.valid ? (
                      <span style={{ color: '#e53e3e', fontWeight: 600 }}>{t.error}</span>
                    ) : t.hidden ? (
                      <span style={{ color: '#718096', fontWeight: 600, background: '#edf2f7', padding: '2px 8px', borderRadius: 4 }}>Скрыта</span>
                    ) : (
                      <span style={{ color: '#2f855a', fontWeight: 600, background: '#f0fff4', padding: '2px 8px', borderRadius: 4 }}>Опубликована</span>
                    )}
                  </td>
                  <td style={{ padding: 10, textAlign: 'right' }}>
                    <div style={{ display: 'inline-flex', gap: 6 }}>
                      {t.valid && (
                        <button
                          onClick={() => toggleTaskVisibility(t.id)}
                          disabled={busy}
                          style={{
                            padding: '4px 10px',
                            background: t.hidden ? '#2b6cb0' : '#edf2f7',
                            color: t.hidden ? '#fff' : '#2d3748',
                            border: '1px solid #cbd5e0',
                            borderRadius: 4,
                            cursor: 'pointer',
                            fontSize: 12
                          }}
                        >
                          {t.hidden ? 'Показать' : 'Скрыть'}
                        </button>
                      )}
                      <button
                        onClick={() => deleteTask(t.id)}
                        disabled={busy}
                        style={{
                          padding: '4px 10px',
                          background: '#fff5f5',
                          color: '#e53e3e',
                          border: '1px solid #fed7d7',
                          borderRadius: 4,
                          cursor: 'pointer',
                          fontSize: 12
                        }}
                      >
                        Удалить
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {/* ВКЛАДКА 2: АНАЛИТИКА СЕССИЙ */}
      {tab === 'sessions' && (
        <div>
          {/* Плашка статуса автобэкапа */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 12, padding: '8px 12px', background: '#f0fff4', border: '1px solid #9ae6b4', borderRadius: 6, fontSize: 12, color: '#22543d' }}>
            <div>
              <strong>🛡 Регулярный автобэкап попыток:</strong> каждые {backupInfo?.interval_minutes ?? 30} мин + мгновенная запись при каждой сдаче
              {backupInfo?.last_backup_at && <span> · Последний снимок: <code>{backupInfo.last_backup_at}</code></span>}
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={triggerManualBackup}
                disabled={busy}
                style={{ padding: '4px 10px', background: '#2f855a', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12, fontWeight: 600 }}
              >
                ⚡ Сделать бэкап сейчас
              </button>
              <button
                onClick={() => downloadBackupFile('latest_backup.zip')}
                style={{ padding: '4px 10px', background: '#fff', color: '#22543d', border: '1px solid #68d391', borderRadius: 4, cursor: 'pointer', fontSize: 12, fontWeight: 600 }}
              >
                📦 Скачать latest_backup.zip
              </button>
            </div>
          </div>

          {/* Панель глобального поиска, фильтров и общей выгрузки */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 16, background: '#f7fafc', padding: 14, borderRadius: 6, border: '1px solid #e2e8f0' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: '1 1 360px', maxWidth: 540 }}>
                <input
                  type="text"
                  placeholder="Поиск по всем работам (код участника, #ID попытки или задача)..."
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      setAppliedQuery(searchInput);
                    }
                  }}
                  style={{ width: '100%', padding: '8px 12px', borderRadius: 4, border: '1px solid #cbd5e0' }}
                />
                {searchInput && (
                  <button
                    onClick={() => { setSearchInput(''); setAppliedQuery(''); }}
                    style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#718096', fontSize: 16 }}
                    title="Очистить поиск"
                  >
                    ✕
                  </button>
                )}
              </div>

              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button
                  onClick={downloadAllCsv}
                  style={{ padding: '7px 12px', background: '#2f855a', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontWeight: 600, fontSize: 12 }}
                  title="Выгрузить сводную таблицу всех попыток с ответами и логами"
                >
                  📥 Ведомость попыток (CSV)
                </button>
                <button
                  onClick={downloadAllEventsCsv}
                  style={{ padding: '7px 12px', background: '#2b6cb0', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontWeight: 600, fontSize: 12 }}
                  title="Выгрузить сквозной хронологический лог всех действий по всем работам в CSV"
                >
                  📋 Лог действий по всем работам (CSV)
                </button>
                <button
                  onClick={downloadFullSessionsJson}
                  style={{ padding: '7px 12px', background: '#4a5568', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontWeight: 600, fontSize: 12 }}
                  title="Выгрузить все работы с подробным журналом действий в JSON"
                >
                  🗂 Все работы + логи (JSON)
                </button>
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12, fontSize: 13 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                  <span>Статус:</span>
                  <select
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                    style={{ padding: '4px 8px', borderRadius: 4, border: '1px solid #cbd5e0', fontSize: 12 }}
                  >
                    <option value="">Все попытки</option>
                    <option value="submitted">Только сданные</option>
                    <option value="in_progress">В процессе</option>
                  </select>
                </label>

                <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', userSelect: 'none' }}>
                  <input
                    type="checkbox"
                    checked={collapseShort}
                    onChange={(e) => setCollapseShort(e.target.checked)}
                  />
                  <span>Группировать и сворачивать короткие (&lt; 5 с) ({shortSessionsCountOnPage} на стр.)</span>
                </label>

                <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', userSelect: 'none' }}>
                  <input
                    type="checkbox"
                    checked={excludeShortServer}
                    onChange={(e) => setExcludeShortServer(e.target.checked)}
                  />
                  <span>Скрыть &lt; 5 с при загрузке с сервера</span>
                </label>
              </div>

              {/* Пагинация */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ color: '#4a5568', fontSize: 12 }}>
                  Всего в базе: <strong>{totalSessions}</strong>
                  {sessions.length > 0 && ` (показаны ${offset + 1}–${offset + sessions.length}, стр. ${currentPage}/${totalPages})`}
                </span>
                <button
                  disabled={busy || !hasPrevPage}
                  onClick={() => void loadSessions(Math.max(0, offset - PAGE_SIZE), false)}
                  style={{ padding: '4px 10px', background: hasPrevPage ? '#edf2f7' : '#f7fafc', color: hasPrevPage ? '#2d3748' : '#a0aec0', border: '1px solid #cbd5e0', borderRadius: 4, cursor: hasPrevPage ? 'pointer' : 'not-allowed', fontSize: 12 }}
                >
                  ← Пред. 100
                </button>
                <button
                  disabled={busy || !hasNextPage}
                  onClick={() => void loadSessions(offset + PAGE_SIZE, false)}
                  style={{ padding: '4px 10px', background: hasNextPage ? '#edf2f7' : '#f7fafc', color: hasNextPage ? '#2d3748' : '#a0aec0', border: '1px solid #cbd5e0', borderRadius: 4, cursor: hasNextPage ? 'pointer' : 'not-allowed', fontSize: 12 }}
                >
                  След. 100 →
                </button>
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', gap: 20 }}>
            <div style={{ flex: selectedEvents ? '1 1 60%' : '1 1 100%' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
                <thead>
                  <tr style={{ background: '#edf2f7', borderBottom: '2px solid #cbd5e0' }}>
                    <th style={{ padding: 8 }}>Попытка</th>
                    <th style={{ padding: 8 }}>Код ученика</th>
                    <th style={{ padding: 8 }}>Задача</th>
                    <th style={{ padding: 8 }}>Время</th>
                    <th style={{ padding: 8 }}>Статус</th>
                    <th style={{ padding: 8 }}>Ответы</th>
                    <th style={{ padding: 8 }}>Экспорт / Логи</th>
                  </tr>
                </thead>
                <tbody>
                  {groupedDisplayRows.map((item) => {
                    if (item.kind === 'single') {
                      return renderSessionRow(item.session, false);
                    }
                    const isOpen = !!expandedGroups[item.groupId];
                    const firstId = item.items[0].attempt_id;
                    const lastId = item.items[item.items.length - 1].attempt_id;
                    const uniqueTasks = Array.from(new Set(item.items.map((x) => x.task_id))).slice(0, 4).join(', ');
                    return (
                      <React.Fragment key={item.groupId}>
                        <tr
                          onClick={() => setExpandedGroups((prev) => ({ ...prev, [item.groupId]: !isOpen }))}
                          style={{
                            background: '#f8fafc',
                            borderBottom: '1px solid #e2e8f0',
                            cursor: 'pointer',
                            color: '#64748b',
                            fontSize: 12
                          }}
                          title="Нажмите, чтобы развернуть или свернуть группу коротких сессий"
                        >
                          <td colSpan={7} style={{ padding: '6px 10px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                              <span>
                                <strong>{isOpen ? '▼' : '▶'} Свёрнуто коротких сессий (&lt; 5 с): {item.items.length} шт.</strong>
                                {' '}
                                <span style={{ color: '#94a3b8' }}>
                                  (попытки #{lastId}…#{firstId}, задачи: {uniqueTasks})
                                </span>
                              </span>
                              <span style={{ color: '#3182ce', fontWeight: 600 }}>
                                {isOpen ? 'Свернуть' : 'Развернуть'}
                              </span>
                            </div>
                          </td>
                        </tr>
                        {isOpen && item.items.map((sub) => renderSessionRow(sub, true))}
                      </React.Fragment>
                    );
                  })}
                  {groupedDisplayRows.length === 0 && (
                    <tr>
                      <td colSpan={7} style={{ padding: 20, textAlign: 'center', color: '#718096' }}>
                        Попыток не найдено.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>

              {/* Нижняя панель догрузки следующей сотни */}
              {sessions.length > 0 && (
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 14, padding: '10px 12px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 6 }}>
                  <span style={{ fontSize: 12, color: '#4a5568' }}>
                    Загружено в таблицу: <strong>{sessions.length}</strong> из <strong>{totalSessions}</strong>
                  </span>
                  <div style={{ display: 'flex', gap: 8 }}>
                    {hasPrevPage && (
                      <button
                        disabled={busy}
                        onClick={() => void loadSessions(Math.max(0, offset - PAGE_SIZE), false)}
                        style={{ padding: '6px 12px', background: '#edf2f7', border: '1px solid #cbd5e0', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
                      >
                        ← Предыдущие 100
                      </button>
                    )}
                    {hasNextPage && (
                      <>
                        <button
                          disabled={busy}
                          onClick={() => void loadSessions(offset + sessions.length, true)}
                          style={{ padding: '6px 14px', background: '#ebf8ff', color: '#2b6cb0', border: '1px solid #90cdf4', borderRadius: 4, cursor: 'pointer', fontSize: 12, fontWeight: 600 }}
                        >
                          + Догрузить ещё 100 в этот список
                        </button>
                        <button
                          disabled={busy}
                          onClick={() => void loadSessions(offset + PAGE_SIZE, false)}
                          style={{ padding: '6px 14px', background: '#3182ce', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12, fontWeight: 600 }}
                        >
                          Перейти к следующей сотне →
                        </button>
                      </>
                    )}
                  </div>
                </div>
              )}
            </div>

            {selectedEvents && (
              <div style={{ flex: '1 1 40%', background: '#f7fafc', padding: 14, borderRadius: 8, border: '1px solid #cbd5e0', maxHeight: 650, overflowY: 'auto' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                  <h4 style={{ margin: 0 }}>Журнал попытки #{activeAttemptId}</h4>
                  <button onClick={() => setSelectedEvents(null)} style={{ border: 'none', background: 'none', cursor: 'pointer', fontWeight: 700 }}>✕</button>
                </div>
                {selectedEvents.length === 0 ? (
                  <p className="muted">Нет записанных действий.</p>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {selectedEvents.map((ev, idx) => (
                      <div key={idx} style={{ background: '#fff', padding: 8, borderRadius: 4, border: '1px solid #e2e8f0', fontSize: 12 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', color: '#718096' }}>
                          <strong>{ev.name}</strong>
                          <span>{ev.time}</span>
                        </div>
                        <div style={{ fontFamily: 'monospace', marginTop: 4, color: '#2d3748', wordBreak: 'break-all' }}>
                          {JSON.stringify(ev.payload)}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ВКЛАДКА 3: РЕЗЕРВНЫЕ КОПИИ ТАБЛИЦЫ ПОПЫТОК */}
      {tab === 'backups' && (
        <div>
          <div style={{ background: '#f8fafc', padding: 16, borderRadius: 8, border: '1px solid #cbd5e0', marginBottom: 20 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
              <div>
                <h4 style={{ margin: '0 0 6px 0' }}>Регулярное резервное копирование таблицы попыток</h4>
                <p style={{ margin: 0, fontSize: 13, color: '#4a5568' }}>
                  Автоматический снимок всей базы попыток (с кодами участников, ответами, оценками и логами действий) выполняется каждые{' '}
                  <strong>{backupInfo?.interval_minutes ?? 30} минут</strong>, а также мгновенно дописывается в журнал{' '}
                  <code>submitted_live_log.csv</code> при каждой сдаче работы.
                </p>
                {backupInfo?.last_backup_at && (
                  <p style={{ margin: '6px 0 0 0', fontSize: 12, color: '#2f855a', fontWeight: 600 }}>
                    Последний полный бэкап: {backupInfo.last_backup_at} ({backupInfo.last_backup_file}) · Всего попыток в снимке: {backupInfo.total_attempts} (сдано: {backupInfo.submitted_attempts})
                  </p>
                )}
                {backupInfo?.last_error && (
                  <p style={{ margin: '6px 0 0 0', fontSize: 12, color: '#e53e3e' }}>
                    Ошибка последнего бэкапа: {backupInfo.last_error}
                  </p>
                )}
              </div>

              <button
                onClick={triggerManualBackup}
                disabled={busy}
                style={{ padding: '8px 16px', background: '#2f855a', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontWeight: 600 }}
              >
                ⚡ Создать полный бэкап сейчас
              </button>
            </div>
          </div>

          <div style={{ background: '#f7fafc', padding: 16, borderRadius: 8, border: '1px solid #e2e8f0', marginBottom: 24 }}>
            <h4 style={{ margin: '0 0 8px 0' }}>Восстановление базы попыток из архива бэкапа (.zip или .json)</h4>
            <p style={{ margin: '0 0 10px 0', fontSize: 12, color: '#718096' }}>
              При переносе сервера или сбое БД загрузите файл <code>latest_backup.zip</code>, <code>backup_*.zip</code> или <code>full_restore_dump.json</code>. Все коды участников, решения, баллы и логи будут безопасно восстановлены.
            </p>
            <form onSubmit={handleRestoreBackup} style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
              <input type="file" accept=".zip,.json" onChange={(e) => setRestoreFile(e.target.files?.[0] || null)} />
              <button
                type="submit"
                disabled={busy || !restoreFile}
                style={{ padding: '6px 14px', background: '#2b6cb0', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontWeight: 600 }}
              >
                Восстановить данные из файла
              </button>
            </form>
          </div>

          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
            <thead>
              <tr style={{ background: '#edf2f7', borderBottom: '2px solid #cbd5e0' }}>
                <th style={{ padding: 10 }}>Файл резервной копии</th>
                <th style={{ padding: 10 }}>Назначение</th>
                <th style={{ padding: 10 }}>Размер</th>
                <th style={{ padding: 10 }}>Обновлён</th>
                <th style={{ padding: 10, textAlign: 'right' }}>Действие</th>
              </tr>
            </thead>
            <tbody>
              {(backupInfo?.files || []).map((f) => {
                let desc = 'Периодический архив (CSV + JSON дамп)';
                if (f.filename === 'latest_backup.zip') desc = 'Актуальный полный архив (попытки + логи + дамп восстановления)';
                else if (f.filename === 'attempts_latest.csv') desc = 'Актуальная таблица всех попыток с кодами участников (Excel CSV)';
                else if (f.filename === 'submitted_live_log.csv') desc = 'Непрерывный live-журнал всех сданных работ (Excel CSV)';
                else if (f.filename === 'submitted_live_log.jsonl') desc = 'Непрерывный live-журнал всех сданных работ (JSONL)';
                else if (f.filename.startsWith('backup_daily_')) desc = 'Ежедневный архивный снимок';

                return (
                  <tr key={f.filename} style={{ borderBottom: '1px solid #e2e8f0', background: f.filename === 'latest_backup.zip' ? '#f0fff4' : '#fff' }}>
                    <td style={{ padding: 10, fontFamily: 'monospace', fontWeight: 600 }}>{f.filename}</td>
                    <td style={{ padding: 10, color: '#4a5568' }}>{desc}</td>
                    <td style={{ padding: 10 }}>{f.size_kb} КБ</td>
                    <td style={{ padding: 10 }}>{f.modified_at}</td>
                    <td style={{ padding: 10, textAlign: 'right' }}>
                      <button
                        onClick={() => downloadBackupFile(f.filename)}
                        style={{ padding: '4px 12px', background: '#3182ce', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
                      >
                        ⬇ Скачать
                      </button>
                    </td>
                  </tr>
                );
              })}
              {(!backupInfo?.files || backupInfo.files.length === 0) && (
                <tr>
                  <td colSpan={5} style={{ padding: 20, textAlign: 'center', color: '#718096' }}>
                    Резервные копии ещё не созданы. Нажмите «Создать полный бэкап сейчас».
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}