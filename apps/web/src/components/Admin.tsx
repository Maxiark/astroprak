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
  backup_type?: string;
  size_kb: number;
  modified_at: string;
}

interface BackupSettings {
  interval_minutes: number;
  auto_backup_type: string;
  keep_count: number;
  keep_daily_count: number;
  gdrive_enabled: boolean;
  gdrive_folder_id: string;
  gdrive_keep_count: number;
  gdrive_client_id: string;
  gdrive_client_secret: string;
  gdrive_refresh_token: string;
  tg_bot_token: string;
  tg_chat_id: string;
  tg_topic_id: string;
}

interface DbSizeInfo {
  db_mb: number;
  attempts_mb: number;
  events_mb: number;
  total_attempts: number;
  bloated_count: number;
}

interface BackupStatusInfo {
  settings: BackupSettings;
  last_backup_at: string | null;
  last_backup_file: string | null;
  last_backup_type: string | null;
  last_gdrive_sync_at: string | null;
  last_gdrive_status: string | null;
  last_tg_send_at: string | null;
  last_error: string | null;
  total_attempts: number;
  submitted_attempts: number;
  total_size_mb: number;
  db_size?: DbSizeInfo;
  files: BackupFileInfo[];
}

type SessionRowOrGroup =
  | { kind: 'single'; session: UserSessionInfo }
  | { kind: 'short_group'; groupId: string; items: UserSessionInfo[] };

const PAGE_SIZE = 100;

const DEFAULT_BACKUP_SETTINGS: BackupSettings = {
  interval_minutes: 360,
  auto_backup_type: 'solutions',
  keep_count: 10,
  keep_daily_count: 7,
  gdrive_enabled: false,
  gdrive_folder_id: '',
  gdrive_keep_count: 10,
  gdrive_client_id: '',
  gdrive_client_secret: '',
  gdrive_refresh_token: '',
  tg_bot_token: '',
  tg_chat_id: '',
  tg_topic_id: '',
};

export function AdminPanel({ onBack }: { onBack: () => void }) {
  const [token, setToken] = useState<string>(() => sessionStorage.getItem('admin_token') || '');
  const [inputToken, setInputToken] = useState('');
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [tab, setTab] = useState<'tasks' | 'sessions' | 'backups'>('tasks');

  const [tasks, setTasks] = useState<TaskAdminInfo[]>([]);

  // Пагинация, глобальный поиск и фильтрация сессий
  const [sessions, setSessions] = useState<UserSessionInfo[]>([]);
  const [totalSessions, setTotalSessions] = useState<number>(0);
  const [hasMoreServer, setHasMoreServer] = useState<boolean>(false);
  const [offset, setOffset] = useState<number>(0);
  const [sessionsLoading, setSessionsLoading] = useState<boolean>(false);
  const [searchInput, setSearchInput] = useState('');
  const [appliedQuery, setAppliedQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('');

  // Кнопка «Скрыть все < 5 с» (независимо от статуса) и группировка
  const [hideAllShort, setHideAllShort] = useState<boolean>(false);
  const [collapseShort, setCollapseShort] = useState<boolean>(true);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});

  const [selectedEvents, setSelectedEvents] = useState<any[] | null>(null);
  const [activeAttemptId, setActiveAttemptId] = useState<number | null>(null);

  // Резервные копии и настройки
  const [backupInfo, setBackupInfo] = useState<BackupStatusInfo | null>(null);
  const [cfgForm, setCfgForm] = useState<BackupSettings>(DEFAULT_BACKUP_SETTINGS);
  const [selectedBackupFiles, setSelectedBackupFiles] = useState<Set<string>>(new Set());
  const [restoreFile, setRestoreFile] = useState<File | null>(null);
  const [showCloudSettings, setShowCloudSettings] = useState<boolean>(false);

  // Категории и drag-and-drop
  const [categoryOrder, setCategoryOrder] = useState<string[]>([]);
  const [draggedCatIndex, setDraggedCatIndex] = useState<number | null>(null);

  const [msg, setMsg] = useState<string | null>(null);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [exportBusy, setExportBusy] = useState<string | null>(null);
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
    setSessionsLoading(true);
    try {
      const qVal = queryOverride !== undefined ? queryOverride : appliedQuery;
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(targetOffset),
      });
      if (qVal.trim()) params.set('q', qVal.trim());
      if (statusFilter) params.set('status_filter', statusFilter);
      if (hideAllShort) params.set('exclude_short', 'true');

      const res = await fetch(`/api/admin/sessions?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        const incoming: UserSessionInfo[] = Array.isArray(data.sessions) ? data.sessions : [];
        const srvTotal = typeof data.total === 'number' ? data.total : null;
        if (srvTotal !== null) {
          setTotalSessions(srvTotal);
          setHasMoreServer(Boolean(data.has_more) || (targetOffset + incoming.length < srvTotal));
        } else {
          // Если отвечает старый бэкенд без поля total — определяем наличие следующей страницы по полноте пачки (100 шт)
          const more = incoming.length >= PAGE_SIZE;
          setHasMoreServer(more);
          setTotalSessions(targetOffset + incoming.length + (more ? PAGE_SIZE : 0));
        }

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
      setSessionsLoading(false);
    }
  }

  async function loadBackups() {
    try {
      const res = await fetch('/api/admin/backups', {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data: BackupStatusInfo = await res.json();
        setBackupInfo(data);
        if (data.settings) {
          setCfgForm({ ...DEFAULT_BACKUP_SETTINGS, ...data.settings });
        }
      }
    } catch (e) {
      console.error(e);
    }
  }

  async function handleSaveBackupSettings(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      const res = await fetch('/api/admin/backups/settings', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify(cfgForm)
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Не удалось сохранить настройки бэкапов');
      setMsg(data.message);
      if (data.state) setBackupInfo((prev) => ({ ...prev, ...data.state, db_size: prev?.db_size }));
      else await loadBackups();
    } catch (err: any) {
      setMsg(`Ошибка сохранения настроек: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function triggerCreateBackup(backupType: 'solutions' | 'csv_only' | 'full', syncGdrive = false) {
    setBusy(true);
    setMsg(null);
    try {
      const res = await fetch('/api/admin/backups/create', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ backup_type: backupType, sync_gdrive: syncGdrive })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Ошибка создания бэкапа');
      setMsg(data.message);
      await loadBackups();
    } catch (e: any) {
      setMsg(`Ошибка бэкапа: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function triggerSendTelegram(filename?: string, backupType: 'solutions' | 'csv_only' | 'full' = 'solutions') {
    setBusy(true);
    setMsg(null);
    try {
      const res = await fetch('/api/admin/backups/send-telegram', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ filename: filename || null, backup_type: backupType })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Ошибка отправки в Telegram');
      setMsg(data.message);
      await loadBackups();
    } catch (e: any) {
      setMsg(`Ошибка Telegram: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function triggerSyncGdrive(filename?: string) {
    setBusy(true);
    setMsg(null);
    try {
      const res = await fetch('/api/admin/backups/sync-gdrive', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ filename: filename || null })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Ошибка выгрузки на Google Диск');
      setMsg(data.message);
      await loadBackups();
    } catch (e: any) {
      setMsg(`Ошибка Google Диска: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function deleteSelectedBackups(filenamesToDelete: string[]) {
    if (filenamesToDelete.length === 0) return;
    const ok = window.confirm(`Удалить выбранные файлы резервных копий (${filenamesToDelete.length} шт.) с диска?`);
    if (!ok) return;

    setBusy(true);
    setMsg(null);
    try {
      const res = await fetch('/api/admin/backups/delete', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ filenames: filenamesToDelete })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Ошибка удаления файлов');
      setMsg(data.message);
      setSelectedBackupFiles((prev) => {
        const next = new Set(prev);
        filenamesToDelete.forEach((f) => next.delete(f));
        return next;
      });
      await loadBackups();
    } catch (e: any) {
      setMsg(`Ошибка удаления: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function handleCompactDatabase(deleteShort: boolean) {
    const promptText = deleteShort
      ? 'Очистить базу от дублирующихся кэшей картинок, удалить все попытки короче 5 секунд и выполнить физическое сжатие тома (VACUUM FULL)?'
      : 'Очистить базу от тяжёлых кэшей картинок (без удаления попыток учеников) и физически сжать дисковый том PostgreSQL (VACUUM FULL)?';
    if (!window.confirm(promptText)) return;

    setBusy(true);
    setMsg('⏳ Выполняется очистка и VACUUM FULL базы данных (может занять 10–30 секунд)...');
    try {
      const res = await fetch('/api/admin/db/compact', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ delete_short_attempts: deleteShort })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Ошибка сжатия БД');
      setMsg(data.message);
      await loadBackups();
      if (tab === 'sessions') await loadSessions(0, false);
    } catch (e: any) {
      setMsg(`Ошибка сжатия БД: ${e.message}`);
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

  function buildExportQueryString(overrideStatus?: string): string {
    const params = new URLSearchParams();
    if (appliedQuery.trim()) params.set('q', appliedQuery.trim());
    const st = overrideStatus !== undefined ? overrideStatus : statusFilter;
    if (st) params.set('status_filter', st);
    if (hideAllShort) params.set('exclude_short', 'true');
    const qs = params.toString();
    return qs ? `?${qs}` : '';
  }

  async function downloadCsv(onlySubmitted = false) {
    const label = onlySubmitted ? 'submitted_csv' : 'all_csv';
    setExportBusy(label);
    try {
      const qs = buildExportQueryString(onlySubmitted ? 'submitted' : undefined);
      const res = await fetch(`/api/admin/sessions/export/csv${qs}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) throw new Error('Не удалось скачать CSV');
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `astrosite_${onlySubmitted ? 'submitted' : 'sessions'}_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (e: any) {
      alert(e.message);
    } finally {
      setExportBusy(null);
    }
  }

  async function downloadAllEventsCsv() {
    setExportBusy('events_csv');
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
    } finally {
      setExportBusy(null);
    }
  }

  async function downloadFullSessionsJson() {
    setExportBusy('full_json');
    try {
      const res = await fetch(`/api/admin/sessions/export/full-json${buildExportQueryString()}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) throw new Error('Не удалось скачать полный JSON логов');
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `astrosite_sessions_with_logs_${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (e: any) {
      alert(e.message);
    } finally {
      setExportBusy(null);
    }
  }

  useEffect(() => {
    if (token) {
      void checkAndLoad(token);
    }
  }, []);

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
  }, [tab, isAuthenticated, appliedQuery, statusFilter, hideAllShort]);

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

  // При включённой кнопке «Скрыть все < 5 с» дополнительно фильтруем и на клиенте все записи < 5 с независимо от статуса
  const visibleSessions = useMemo(() => {
    const list = sessions || [];
    if (!hideAllShort) return list;
    return list.filter((s) => (s.duration_sec || 0) >= 5);
  }, [sessions, hideAllShort]);

  // Группировка подряд идущих коротких (< 5 с) сессий (если они не скрыты полностью)
  const groupedDisplayRows = useMemo<SessionRowOrGroup[]>(() => {
    if (!collapseShort || hideAllShort) {
      return visibleSessions.map((s) => ({ kind: 'single', session: s }));
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

    for (const s of visibleSessions) {
      const isShort = (s.duration_sec || 0) < 5;
      if (isShort) {
        buffer.push(s);
      } else {
        flushBuffer();
        out.push({ kind: 'single', session: s });
      }
    }
    flushBuffer();
    return out;
  }, [visibleSessions, collapseShort, hideAllShort]);

  const shortSessionsCountOnPage = useMemo(
    () => (sessions || []).filter((s) => (s.duration_sec || 0) < 5).length,
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
          opacity: s.duration_sec < 5 ? 0.82 : 1
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
  const hasNextPage = hasMoreServer || (totalSessions > offset + sessions.length) || (sessions.length >= PAGE_SIZE);
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(currentPage + (hasNextPage ? 1 : 0), Math.ceil(totalSessions / PAGE_SIZE));

  const allFilesList = backupInfo?.files || [];
  const allFilesSelected = allFilesList.length > 0 && allFilesList.every((f) => selectedBackupFiles.has(f.filename));

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
        <h2>Администрирование Astrosite v2.2</h2>
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
          Резервные копии и диск БД ({allFilesList.length})
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
          {/* Плашка статуса автобэкапа и объёма БД */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 12, padding: '8px 12px', background: '#f0fff4', border: '1px solid #9ae6b4', borderRadius: 6, fontSize: 12, color: '#22543d' }}>
            <div>
              <strong>🛡 Бэкап:</strong> каждые {backupInfo?.settings?.interval_minutes ?? 360} мин (тип: <code>{backupInfo?.settings?.auto_backup_type ?? 'solutions'}</code>)
              {backupInfo?.db_size && (
                <span>
                  {' '}· <strong>Объём БД: {backupInfo.db_size.db_mb} МБ</strong>
                  {backupInfo.db_size.bloated_count > 0 && (
                    <span style={{ color: '#c53030', fontWeight: 700 }}>
                      {' '}(есть {backupInfo.db_size.bloated_count} неочищенных записей с кэшем картинок — сожмите БД во вкладке «Резервные копии»!)
                    </span>
                  )}
                </span>
              )}
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={() => void triggerCreateBackup('solutions', false)}
                disabled={busy}
                style={{ padding: '4px 10px', background: '#2f855a', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12, fontWeight: 600 }}
              >
                ⚡ Бэкап решений
              </button>
              <button
                onClick={() => void triggerSendTelegram(undefined, 'solutions')}
                disabled={busy}
                style={{ padding: '4px 10px', background: '#0284c7', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12, fontWeight: 600 }}
              >
                ✈️ Выгрузить в ТГ
              </button>
            </div>
          </div>

          {/* Панель глобального поиска, фильтров и общей выгрузки */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 14, background: '#f7fafc', padding: 14, borderRadius: 6, border: '1px solid #e2e8f0' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: '1 1 340px', maxWidth: 500 }}>
                <input
                  type="text"
                  placeholder="Поиск по всем работам в базе (код участника, #ID попытки или задача)..."
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
                  onClick={() => void downloadCsv(true)}
                  disabled={!!exportBusy}
                  style={{ padding: '7px 12px', background: '#16a34a', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontWeight: 600, fontSize: 12 }}
                  title="Быстрая выгрузка только сданных работ с баллами (компактный Excel CSV)"
                >
                  {exportBusy === 'submitted_csv' ? '⏳ Выгрузка...' : '📥 Сданные работы (CSV)'}
                </button>
                <button
                  onClick={() => void downloadCsv(false)}
                  disabled={!!exportBusy}
                  style={{ padding: '7px 12px', background: '#2f855a', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontWeight: 600, fontSize: 12 }}
                  title="Выгрузить все попытки по текущему фильтру в CSV"
                >
                  {exportBusy === 'all_csv' ? '⏳ Выгрузка...' : '📥 Все попытки (CSV)'}
                </button>
                <button
                  onClick={downloadAllEventsCsv}
                  disabled={!!exportBusy}
                  style={{ padding: '7px 12px', background: '#2b6cb0', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontWeight: 600, fontSize: 12 }}
                  title="Выгрузить сквозной хронологический лог всех действий по всем работам в CSV"
                >
                  {exportBusy === 'events_csv' ? '⏳ Выгрузка...' : '📋 Лог действий всех работ (CSV)'}
                </button>
                <button
                  onClick={downloadFullSessionsJson}
                  disabled={!!exportBusy}
                  style={{ padding: '7px 12px', background: '#4a5568', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontWeight: 600, fontSize: 12 }}
                  title="Выгрузить содержательные работы с журналом действий в JSON"
                >
                  {exportBusy === 'full_json' ? '⏳ Выгрузка...' : '🗂 Работы + логи (JSON)'}
                </button>
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12, fontSize: 13 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span>Статус:</span>
                  <select
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                    style={{ padding: '5px 8px', borderRadius: 4, border: '1px solid #cbd5e0', fontSize: 12 }}
                  >
                    <option value="">Все попытки</option>
                    <option value="submitted">Только сданные</option>
                    <option value="in_progress">В процессе</option>
                  </select>
                </label>

                {/* Кнопка «Скрыть все < 5 с» (независимо от статуса) */}
                <button
                  type="button"
                  onClick={() => setHideAllShort((v) => !v)}
                  style={{
                    padding: '6px 12px',
                    background: hideAllShort ? '#dc2626' : '#fff',
                    color: hideAllShort ? '#fff' : '#2d3748',
                    border: `1px solid ${hideAllShort ? '#dc2626' : '#cbd5e0'}`,
                    borderRadius: 4,
                    cursor: 'pointer',
                    fontSize: 12,
                    fontWeight: 700
                  }}
                  title="Полностью скрыть все попытки длительностью менее 5 секунд независимо от того, сданы они или нет"
                >
                  {hideAllShort ? '✓ Скрыты все < 5 с (нажмите, чтобы показать)' : `🚫 Скрыть все < 5 с (${shortSessionsCountOnPage} на стр.)`}
                </button>

                {!hideAllShort && (
                  <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', userSelect: 'none' }}>
                    <input
                      type="checkbox"
                      checked={collapseShort}
                      onChange={(e) => setCollapseShort(e.target.checked)}
                    />
                    <span>Сворачивать &lt; 5 с в группы</span>
                  </label>
                )}
              </div>

              {/* Верхняя панель пагинации («Предыдущие 100» / «Следующие 100») */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, background: '#fff', padding: '6px 10px', borderRadius: 6, border: '1px solid #cbd5e0' }}>
                <span style={{ color: '#2d3748', fontSize: 12 }}>
                  Всего: <strong>{totalSessions}</strong>
                  {sessions.length > 0 && ` · Показаны ${offset + 1}–${offset + sessions.length} (стр. ${currentPage}/${totalPages})`}
                </span>
                <button
                  disabled={sessionsLoading || !hasPrevPage}
                  onClick={() => void loadSessions(Math.max(0, offset - PAGE_SIZE), false)}
                  style={{ padding: '5px 12px', background: hasPrevPage ? '#edf2f7' : '#f7fafc', color: hasPrevPage ? '#2d3748' : '#a0aec0', border: '1px solid #cbd5e0', borderRadius: 4, cursor: hasPrevPage ? 'pointer' : 'not-allowed', fontSize: 12, fontWeight: 600 }}
                >
                  ← Предыдущие 100
                </button>
                <button
                  disabled={sessionsLoading || !hasNextPage}
                  onClick={() => void loadSessions(offset + PAGE_SIZE, false)}
                  style={{ padding: '5px 12px', background: hasNextPage ? '#3182ce' : '#f7fafc', color: hasNextPage ? '#fff' : '#a0aec0', border: 'none', borderRadius: 4, cursor: hasNextPage ? 'pointer' : 'not-allowed', fontSize: 12, fontWeight: 600 }}
                >
                  Следующие 100 →
                </button>
              </div>
            </div>
          </div>

          {sessionsLoading && (
            <div style={{ padding: '14px 16px', marginBottom: 14, background: '#ebf8ff', color: '#2b6cb0', border: '1px solid #90cdf4', borderRadius: 6, fontWeight: 600, fontSize: 13 }}>
              ⏳ Загрузка записей попыток с сервера...
            </div>
          )}

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
                  {!sessionsLoading && groupedDisplayRows.length === 0 && (
                    <tr>
                      <td colSpan={7} style={{ padding: 20, textAlign: 'center', color: '#718096' }}>
                        Попыток не найдено.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>

              {/* Нижняя панель навигации по сотням работ */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginTop: 14, padding: '12px 14px', background: '#f8fafc', border: '1px solid #cbd5e0', borderRadius: 6 }}>
                <span style={{ fontSize: 13, color: '#2d3748' }}>
                  Страница <strong>{currentPage}</strong> из <strong>{totalPages}</strong> · Отображено <strong>{visibleSessions.length}</strong> записей (всего по фильтру: <strong>{totalSessions}</strong>)
                </span>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <button
                    disabled={sessionsLoading || !hasPrevPage}
                    onClick={() => void loadSessions(Math.max(0, offset - PAGE_SIZE), false)}
                    style={{ padding: '7px 14px', background: hasPrevPage ? '#edf2f7' : '#f7fafc', color: hasPrevPage ? '#2d3748' : '#a0aec0', border: '1px solid #cbd5e0', borderRadius: 4, cursor: hasPrevPage ? 'pointer' : 'not-allowed', fontSize: 13, fontWeight: 600 }}
                  >
                    ← Предыдущие 100
                  </button>
                  <button
                    disabled={sessionsLoading || !hasNextPage}
                    onClick={() => void loadSessions(offset + sessions.length, true)}
                    style={{ padding: '7px 14px', background: hasNextPage ? '#ebf8ff' : '#f7fafc', color: hasNextPage ? '#2b6cb0' : '#a0aec0', border: '1px solid #90cdf4', borderRadius: 4, cursor: hasNextPage ? 'pointer' : 'not-allowed', fontSize: 13, fontWeight: 600 }}
                  >
                    + Догрузить ещё 100 в таблицу
                  </button>
                  <button
                    disabled={sessionsLoading || !hasNextPage}
                    onClick={() => void loadSessions(offset + PAGE_SIZE, false)}
                    style={{ padding: '7px 16px', background: hasNextPage ? '#3182ce' : '#cbd5e0', color: '#fff', border: 'none', borderRadius: 4, cursor: hasNextPage ? 'pointer' : 'not-allowed', fontSize: 13, fontWeight: 700 }}
                  >
                    Следующие 100 →
                  </button>
                </div>
              </div>
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

      {/* ВКЛАДКА 3: РЕЗЕРВНЫЕ КОПИИ, СЖАТИЕ БД И ОБЛАЧНАЯ ВЫГРУЗКА */}
      {tab === 'backups' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* 1. Управление объёмом БД PostgreSQL (исправление проблемы 12 ГБ) */}
          <div style={{ background: '#fff5f5', padding: 16, borderRadius: 8, border: '1px solid #feb2b2' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
              <div>
                <h4 style={{ margin: '0 0 6px 0', color: '#9b2c2c' }}>
                  💾 Дисковый объём базы данных PostgreSQL: {backupInfo?.db_size?.db_mb ?? '—'} МБ
                </h4>
                <p style={{ margin: 0, fontSize: 13, color: '#742a2a' }}>
                  Таблица попыток (<code>attempts</code>): <strong>{backupInfo?.db_size?.attempts_mb ?? '—'} МБ</strong> · Таблица логов (<code>events</code>): <strong>{backupInfo?.db_size?.events_mb ?? '—'} МБ</strong> · Записей со старым base64-кэшем картинок: <strong>{backupInfo?.db_size?.bloated_count ?? 0}</strong>.
                </p>
                <p style={{ margin: '4px 0 0 0', fontSize: 12, color: '#9b2c2c' }}>
                  Нажмите кнопку справа, чтобы очистить дублирующиеся 500 КБ base64-картинки из старых строк и выполнить <code>VACUUM FULL</code> (уменьшает том с ~12 ГБ до ~20 МБ без потери ответов и баллов).
                </p>
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button
                  onClick={() => void handleCompactDatabase(false)}
                  disabled={busy}
                  style={{ padding: '8px 14px', background: '#c53030', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontWeight: 700, fontSize: 12 }}
                >
                  🧹 Сжать БД (очистить кэш картинок + VACUUM FULL)
                </button>
                <button
                  onClick={() => void handleCompactDatabase(true)}
                  disabled={busy}
                  style={{ padding: '8px 14px', background: '#742a2a', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontWeight: 600, fontSize: 12 }}
                >
                  🗑 Удалить все попытки &lt; 5 с + Сжать БД
                </button>
              </div>
            </div>
          </div>

          {/* 2. Три типа резервных копий и выгрузка по команде */}
          <div style={{ background: '#f8fafc', padding: 16, borderRadius: 8, border: '1px solid #cbd5e0' }}>
            <h4 style={{ margin: '0 0 12px 0' }}>Создание резервных копий по типам и отправка в Telegram</h4>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 14 }}>
              {/* Тип 1: Компактный бэкап решений */}
              <div style={{ background: '#fff', padding: 14, borderRadius: 6, border: '2px solid #68d391', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 14, color: '#22543d', marginBottom: 4 }}>
                    1. Компактный бэкап решений (Рекомендуется)
                  </div>
                  <p style={{ fontSize: 12, color: '#4a5568', margin: '0 0 12px 0' }}>
                    Включает <strong>только сданные работы и попытки с непустыми ответами</strong> (коды участников, баллы, ответы, протоколы проверки). Содержит CSV для Excel + JSON для полного восстановления решений. Весит десятки КБ.
                  </p>
                </div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <button
                    onClick={() => void triggerCreateBackup('solutions', false)}
                    disabled={busy}
                    style={{ padding: '6px 12px', background: '#2f855a', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12, fontWeight: 600 }}
                  >
                    ⚡ Создать на диске
                  </button>
                  <button
                    onClick={() => void triggerSendTelegram(undefined, 'solutions')}
                    disabled={busy}
                    style={{ padding: '6px 12px', background: '#0284c7', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12, fontWeight: 600 }}
                  >
                    ✈️ Создать и отправить в ТГ
                  </button>
                </div>
              </div>

              {/* Тип 2: Ведомость CSV */}
              <div style={{ background: '#fff', padding: 14, borderRadius: 6, border: '1px solid #cbd5e0', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 14, color: '#2d3748', marginBottom: 4 }}>
                    2. Сводная ведомость всех попыток (CSV)
                  </div>
                  <p style={{ fontSize: 12, color: '#4a5568', margin: '0 0 12px 0' }}>
                    Один плоский файл <code>.csv</code> (UTF-8 для Excel) со всеми попытками, кодами участников, баллами, датами и ответами без логов кликов и системных дампов.
                  </p>
                </div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <button
                    onClick={() => void triggerCreateBackup('csv_only', false)}
                    disabled={busy}
                    style={{ padding: '6px 12px', background: '#3182ce', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12, fontWeight: 600 }}
                  >
                    📄 Создать таблицу CSV
                  </button>
                  <button
                    onClick={() => void triggerSendTelegram(undefined, 'csv_only')}
                    disabled={busy}
                    style={{ padding: '6px 12px', background: '#0284c7', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12, fontWeight: 600 }}
                  >
                    ✈️ Отправить CSV в ТГ
                  </button>
                </div>
              </div>

              {/* Тип 3: Полный системный архив */}
              <div style={{ background: '#fff', padding: 14, borderRadius: 6, border: '1px solid #cbd5e0', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 14, color: '#2d3748', marginBottom: 4 }}>
                    3. Полный системный дамп (ZIP)
                  </div>
                  <p style={{ fontSize: 12, color: '#4a5568', margin: '0 0 12px 0' }}>
                    Полный архив всей базы (все попытки + полный журнал всех действий <code>events_log.csv</code> + дамп восстановления <code>full_restore_dump.json</code>).
                  </p>
                </div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <button
                    onClick={() => void triggerCreateBackup('full', false)}
                    disabled={busy}
                    style={{ padding: '6px 12px', background: '#4a5568', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12, fontWeight: 600 }}
                  >
                    📦 Создать полный ZIP
                  </button>
                  <button
                    onClick={() => void triggerSendTelegram(undefined, 'full')}
                    disabled={busy}
                    style={{ padding: '6px 12px', background: '#0284c7', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12, fontWeight: 600 }}
                  >
                    ✈️ Отправить полный в ТГ
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* 3. Настройки интервалов, Google Диска и Telegram */}
          <form onSubmit={handleSaveBackupSettings} style={{ background: '#f8fafc', padding: 16, borderRadius: 8, border: '1px solid #cbd5e0' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <h4 style={{ margin: 0 }}>⚙ Настройки расписания, лимитов хранения, Google Диска и Telegram</h4>
              <button
                type="button"
                onClick={() => setShowCloudSettings((v) => !v)}
                style={{ padding: '4px 10px', background: '#edf2f7', border: '1px solid #cbd5e0', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
              >
                {showCloudSettings ? '▲ Скрыть ключи Google Диска / Telegram' : '▼ Настроить ключи Google Диска и Telegram'}
              </button>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 12, marginBottom: 12 }}>
              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>
                  Интервал автобэкапа (минут, 0 = выкл):
                </label>
                <input
                  type="number"
                  min={0}
                  value={cfgForm.interval_minutes}
                  onChange={(e) => setCfgForm({ ...cfgForm, interval_minutes: parseInt(e.target.value, 10) || 0 })}
                  style={{ width: '100%', padding: '6px 8px', borderRadius: 4, border: '1px solid #cbd5e0', boxSizing: 'border-box' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>
                  Тип регулярного автобэкапа:
                </label>
                <select
                  value={cfgForm.auto_backup_type}
                  onChange={(e) => setCfgForm({ ...cfgForm, auto_backup_type: e.target.value })}
                  style={{ width: '100%', padding: '6px 8px', borderRadius: 4, border: '1px solid #cbd5e0', boxSizing: 'border-box' }}
                >
                  <option value="solutions">1. Компактный бэкап решений (рекомендуется)</option>
                  <option value="csv_only">2. Только таблица CSV</option>
                  <option value="full">3. Полный системный дамп ZIP</option>
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>
                  Хранить периодических копий на сервере:
                </label>
                <input
                  type="number"
                  min={1}
                  max={200}
                  value={cfgForm.keep_count}
                  onChange={(e) => setCfgForm({ ...cfgForm, keep_count: parseInt(e.target.value, 10) || 1 })}
                  style={{ width: '100%', padding: '6px 8px', borderRadius: 4, border: '1px solid #cbd5e0', boxSizing: 'border-box' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>
                  Хранить ежедневных копий на сервере:
                </label>
                <input
                  type="number"
                  min={1}
                  max={90}
                  value={cfgForm.keep_daily_count}
                  onChange={(e) => setCfgForm({ ...cfgForm, keep_daily_count: parseInt(e.target.value, 10) || 1 })}
                  style={{ width: '100%', padding: '6px 8px', borderRadius: 4, border: '1px solid #cbd5e0', boxSizing: 'border-box' }}
                />
              </div>
            </div>

            {showCloudSettings && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, padding: 12, background: '#fff', borderRadius: 6, border: '1px solid #e2e8f0', marginBottom: 12 }}>
                {/* Google Drive */}
                <div>
                  <h5 style={{ margin: '0 0 8px 0', color: '#2b6cb0' }}>☁️ Регулярная автовыгрузка на Google Диск (с автоудалением старых)</h5>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, marginBottom: 8, cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={cfgForm.gdrive_enabled}
                      onChange={(e) => setCfgForm({ ...cfgForm, gdrive_enabled: e.target.checked })}
                    />
                    <strong>Автоматически отправлять регулярные бэкапы на Google Диск</strong>
                  </label>
                  <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 8, marginBottom: 8 }}>
                    <div>
                      <label style={{ fontSize: 11, color: '#4a5568' }}>ID папки на Google Диске (Folder ID):</label>
                      <input
                        type="text"
                        placeholder="Напр. 1A2B3C4D5E6F..."
                        value={cfgForm.gdrive_folder_id}
                        onChange={(e) => setCfgForm({ ...cfgForm, gdrive_folder_id: e.target.value })}
                        style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 4, border: '1px solid #cbd5e0', boxSizing: 'border-box' }}
                      />
                    </div>
                    <div>
                      <label style={{ fontSize: 11, color: '#4a5568' }}>Хранить копий на Диске:</label>
                      <input
                        type="number"
                        min={1}
                        max={100}
                        value={cfgForm.gdrive_keep_count}
                        onChange={(e) => setCfgForm({ ...cfgForm, gdrive_keep_count: parseInt(e.target.value, 10) || 10 })}
                        style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 4, border: '1px solid #cbd5e0', boxSizing: 'border-box' }}
                      />
                    </div>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <input
                      type="text"
                      placeholder="OAuth2 Client ID (из Google Cloud Console)"
                      value={cfgForm.gdrive_client_id}
                      onChange={(e) => setCfgForm({ ...cfgForm, gdrive_client_id: e.target.value })}
                      style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 4, border: '1px solid #cbd5e0', boxSizing: 'border-box' }}
                    />
                    <input
                      type="password"
                      placeholder="OAuth2 Client Secret"
                      value={cfgForm.gdrive_client_secret}
                      onChange={(e) => setCfgForm({ ...cfgForm, gdrive_client_secret: e.target.value })}
                      style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 4, border: '1px solid #cbd5e0', boxSizing: 'border-box' }}
                    />
                    <input
                      type="password"
                      placeholder="OAuth2 Refresh Token (с правом drive.file)"
                      value={cfgForm.gdrive_refresh_token}
                      onChange={(e) => setCfgForm({ ...cfgForm, gdrive_refresh_token: e.target.value })}
                      style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 4, border: '1px solid #cbd5e0', boxSizing: 'border-box' }}
                    />
                  </div>
                  {backupInfo?.last_gdrive_status && (
                    <div style={{ fontSize: 11, color: '#2b6cb0', marginTop: 6 }}>
                      Статус Google Диска: {backupInfo.last_gdrive_status} ({backupInfo.last_gdrive_sync_at})
                    </div>
                  )}
                </div>

                {/* Telegram */}
                <div>
                  <h5 style={{ margin: '0 0 8px 0', color: '#0284c7' }}>✈️ Выгрузка бэкапов в Telegram по команде</h5>
                  <p style={{ fontSize: 11, color: '#64748b', margin: '0 0 8px 0' }}>
                    Укажите токен бота и ID чата/супергруппы. При нажатии «✈️ В Telegram» выбранный архив придёт документом в чат.
                  </p>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <input
                      type="password"
                      placeholder="Telegram Bot Token (напр. 123456:ABC-DEF...)"
                      value={cfgForm.tg_bot_token}
                      onChange={(e) => setCfgForm({ ...cfgForm, tg_bot_token: e.target.value })}
                      style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 4, border: '1px solid #cbd5e0', boxSizing: 'border-box' }}
                    />
                    <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 8 }}>
                      <input
                        type="text"
                        placeholder="Chat ID (напр. -1001234567890)"
                        value={cfgForm.tg_chat_id}
                        onChange={(e) => setCfgForm({ ...cfgForm, tg_chat_id: e.target.value })}
                        style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 4, border: '1px solid #cbd5e0', boxSizing: 'border-box' }}
                      />
                      <input
                        type="text"
                        placeholder="Topic ID (необяз.)"
                        value={cfgForm.tg_topic_id}
                        onChange={(e) => setCfgForm({ ...cfgForm, tg_topic_id: e.target.value })}
                        style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 4, border: '1px solid #cbd5e0', boxSizing: 'border-box' }}
                      />
                    </div>
                  </div>
                  {backupInfo?.last_tg_send_at && (
                    <div style={{ fontSize: 11, color: '#0284c7', marginTop: 6 }}>
                      Последняя отправка в ТГ: {backupInfo.last_tg_send_at}
                    </div>
                  )}
                </div>
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 12, color: '#64748b' }}>
                Всего файлов бэкапов на сервере: <strong>{allFilesList.length}</strong> (общий размер: <strong>{backupInfo?.total_size_mb ?? 0} МБ</strong>)
              </span>
              <div style={{ display: 'flex', gap: 8 }}>
                {cfgForm.gdrive_folder_id && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void triggerSyncGdrive()}
                    style={{ padding: '6px 14px', background: '#2b6cb0', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12, fontWeight: 600 }}
                  >
                    ☁️ Проверить выгрузку на Google Диск сейчас
                  </button>
                )}
                <button
                  type="submit"
                  disabled={busy}
                  style={{ padding: '6px 16px', background: '#2f855a', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12, fontWeight: 700 }}
                >
                  💾 Сохранить настройки бэкапов
                </button>
              </div>
            </div>
          </form>

          {/* 4. Таблица файлов бэкапов с множественным выделением и удалением */}
          <div style={{ background: '#fff', borderRadius: 8, border: '1px solid #cbd5e0', overflow: 'hidden' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, padding: '10px 14px', background: '#f8fafc', borderBottom: '1px solid #cbd5e0' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <strong style={{ fontSize: 13 }}>Файлы резервных копий на сервере ({allFilesList.length})</strong>
                <button
                  type="button"
                  onClick={() => {
                    const nonLatest = allFilesList
                      .map((f) => f.filename)
                      .filter((name) => !['latest_backup.zip', 'attempts_latest.csv', 'submitted_live_log.csv', 'submitted_live_log.jsonl'].includes(name));
                    setSelectedBackupFiles(new Set(nonLatest));
                  }}
                  style={{ padding: '3px 8px', background: '#edf2f7', border: '1px solid #cbd5e0', borderRadius: 4, cursor: 'pointer', fontSize: 11 }}
                >
                  Выделить все архивные снимки (кроме latest/live)
                </button>
              </div>

              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                {selectedBackupFiles.size > 0 && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void deleteSelectedBackups(Array.from(selectedBackupFiles))}
                    style={{ padding: '5px 12px', background: '#e53e3e', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12, fontWeight: 700 }}
                  >
                    🗑 Удалить выбранные ({selectedBackupFiles.size})
                  </button>
                )}
              </div>
            </div>

            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
              <thead>
                <tr style={{ background: '#edf2f7', borderBottom: '2px solid #cbd5e0' }}>
                  <th style={{ padding: 10, width: 36, textAlign: 'center' }}>
                    <input
                      type="checkbox"
                      checked={allFilesSelected}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSelectedBackupFiles(new Set(allFilesList.map((f) => f.filename)));
                        } else {
                          setSelectedBackupFiles(new Set());
                        }
                      }}
                    />
                  </th>
                  <th style={{ padding: 10 }}>Файл</th>
                  <th style={{ padding: 10 }}>Тип / Описание</th>
                  <th style={{ padding: 10 }}>Размер</th>
                  <th style={{ padding: 10 }}>Обновлён</th>
                  <th style={{ padding: 10, textAlign: 'right' }}>Действия</th>
                </tr>
              </thead>
              <tbody>
                {allFilesList.map((f) => {
                  const isChecked = selectedBackupFiles.has(f.filename);
                  let desc = 'Полный системный архив (ZIP)';
                  if (f.filename === 'latest_backup.zip') desc = 'Актуальный архив для быстрого восстановления';
                  else if (f.filename.startsWith('solutions_')) desc = 'Компактный бэкап решений (сданные + черновики)';
                  else if (f.filename === 'attempts_latest.csv' || f.filename.startsWith('attempts_table_')) desc = 'Сводная таблица всех попыток (Excel CSV)';
                  else if (f.filename === 'submitted_live_log.csv') desc = 'Непрерывный live-журнал сданных работ (Excel CSV)';
                  else if (f.filename === 'submitted_live_log.jsonl') desc = 'Непрерывный live-журнал сданных работ (JSONL)';
                  else if (f.filename.startsWith('backup_daily_')) desc = 'Ежедневный архивный снимок';

                  return (
                    <tr
                      key={f.filename}
                      style={{
                        borderBottom: '1px solid #e2e8f0',
                        background: isChecked ? '#fff5f5' : f.filename === 'latest_backup.zip' ? '#f0fff4' : '#fff'
                      }}
                    >
                      <td style={{ padding: 10, textAlign: 'center' }}>
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={(e) => {
                            setSelectedBackupFiles((prev) => {
                              const next = new Set(prev);
                              if (e.target.checked) next.add(f.filename);
                              else next.delete(f.filename);
                              return next;
                            });
                          }}
                        />
                      </td>
                      <td style={{ padding: 10, fontFamily: 'monospace', fontWeight: 600 }}>{f.filename}</td>
                      <td style={{ padding: 10, color: '#4a5568', fontSize: 12 }}>{desc}</td>
                      <td style={{ padding: 10 }}>{f.size_kb} КБ</td>
                      <td style={{ padding: 10, fontSize: 12 }}>{f.modified_at}</td>
                      <td style={{ padding: 10, textAlign: 'right' }}>
                        <div style={{ display: 'inline-flex', gap: 6 }}>
                          <button
                            onClick={() => void downloadBackupFile(f.filename)}
                            style={{ padding: '4px 10px', background: '#3182ce', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
                          >
                            ⬇ Скачать
                          </button>
                          <button
                            onClick={() => void triggerSendTelegram(f.filename)}
                            disabled={busy}
                            style={{ padding: '4px 10px', background: '#0284c7', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
                            title="Отправить этот файл в Telegram"
                          >
                            ✈️ В ТГ
                          </button>
                          <button
                            onClick={() => void triggerSyncGdrive(f.filename)}
                            disabled={busy}
                            style={{ padding: '4px 10px', background: '#edf2f7', color: '#2d3748', border: '1px solid #cbd5e0', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
                            title="Выгрузить этот файл на Google Диск"
                          >
                            ☁️ Диск
                          </button>
                          <button
                            onClick={() => void deleteSelectedBackups([f.filename])}
                            disabled={busy}
                            style={{ padding: '4px 8px', background: '#fff5f5', color: '#e53e3e', border: '1px solid #fed7d7', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
                            title="Удалить файл с сервера"
                          >
                            ✕
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {allFilesList.length === 0 && (
                  <tr>
                    <td colSpan={6} style={{ padding: 20, textAlign: 'center', color: '#718096' }}>
                      Файлов резервных копий пока нет.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* 5. Восстановление из бэкапа */}
          <div style={{ background: '#f7fafc', padding: 16, borderRadius: 8, border: '1px solid #e2e8f0' }}>
            <h4 style={{ margin: '0 0 8px 0' }}>Восстановление базы попыток из архива бэкапа (.zip или .json)</h4>
            <p style={{ margin: '0 0 10px 0', fontSize: 12, color: '#718096' }}>
              Загрузите архив <code>solutions_*.zip</code>, <code>latest_backup.zip</code>, <code>backup_*.zip</code> или <code>full_restore_dump.json</code> для идемпотентного восстановления всех кодов участников, ответов и оценок.
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
        </div>
      )}
    </div>
  );
}