// apps/web/src/App.tsx
import { useEffect, useState, useMemo, useRef } from 'react';
import { api, type Attempt, type TaskManifest } from './api';
import { Workbench } from './components/Workbench';
import { AdminPanel } from './components/Admin';

type SessionStatus = 'loading' | 'ready' | 'switching' | 'expired' | 'error';

function taskIdFromPath(): string | null {
  const m = location.pathname.match(/^\/task\/([a-zA-Z0-9_-]+)$/);
  return m ? m[1] : null;
}

export function App() {
  const [sessionStatus, setSessionStatus] = useState<SessionStatus>('loading');
  const [sessionVersion, setSessionVersion] = useState<number>(1);
  const [recoveryCode, setRecoveryCode] = useState<string | null>(null);

  const [tasks, setTasks] = useState<TaskManifest[]>([]);
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [activeTheory, setActiveTheory] = useState<TaskManifest | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [restoreInput, setRestoreInput] = useState('');
  const [restoreMsg, setRestoreMsg] = useState<string | null>(null);
  const [keyPanelOpen, setKeyPanelOpen] = useState(false);

  const [searchQuery, setSearchQuery] = useState('');
  const [selectedClass, setSelectedClass] = useState<number | null>(null);
  const [viewAdmin, setViewAdmin] = useState(location.pathname === '/admin');
  const [categoryOrder, setCategoryOrder] = useState<string[]>([]);

  const channelRef = useRef<BroadcastChannel | null>(null);

  // 1. Инициализация сессии и BroadcastChannel
  useEffect(() => {
    if (typeof BroadcastChannel !== 'undefined') {
      const bc = new BroadcastChannel('astrosite_session_sync');
      channelRef.current = bc;
      bc.onmessage = (event) => {
        if (event.data?.type === 'SESSION_CHANGED') {
          setSessionStatus('switching');
          void reloadSession(false);
        }
      };
    }

    async function bootstrap() {
      try {
        const res = await fetch('/api/me', { cache: 'no-store' });
        if (!res.ok) throw new Error('Не удалось получить сессию');
        const data = await res.json();
        setRecoveryCode(data.recovery_code);
        setSessionStatus('ready');
      } catch (err: any) {
        setSessionStatus('error');
        setError(err.message || 'Ошибка инициализации сессии');
      }
    }

    void bootstrap();

    const onFocus = () => {
      if (document.visibilityState === 'visible') {
        void checkSessionDrift();
      }
    };
    window.addEventListener('focus', onFocus);
    window.addEventListener('visibilitychange', onFocus);

    return () => {
      window.removeEventListener('focus', onFocus);
      window.removeEventListener('visibilitychange', onFocus);
      if (channelRef.current) channelRef.current.close();
    };
  }, []);

  // 2. Обработка навигации из iframes теории (без вложенных копий сайта)
  useEffect(() => {
    const handleFrameNav = (e: MessageEvent) => {
      if (e.origin !== window.location.origin) return;
      if (e.data?.type === 'ASTROSITE_NAVIGATE_TASK' && typeof e.data.task_id === 'string') {
        void openTaskOrTheory(e.data.task_id);
      }
    };
    window.addEventListener('message', handleFrameNav);
    return () => window.removeEventListener('message', handleFrameNav);
  }, [tasks]);

  // 3. Загрузка контента ТОЛЬКО после наступления статуса 'ready'
  useEffect(() => {
    if (sessionStatus !== 'ready') return;

    fetch('/api/categories')
      .then((r) => r.json())
      .then((d) => setCategoryOrder(d.categories || []))
      .catch(() => {});

    const directId = taskIdFromPath();
    if (viewAdmin) return;
    if (directId) {
      void openTaskOrTheory(directId);
    } else {
      void loadCatalogue();
    }
  }, [sessionStatus, viewAdmin]);

  async function checkSessionDrift() {
    try {
      const res = await fetch('/api/me', { cache: 'no-store' });
      if (res.ok) {
        const data = await res.json();
        if (recoveryCode && data.recovery_code !== recoveryCode) {
          setSessionStatus('switching');
          void reloadSession(false);
        }
      }
    } catch {}
  }

  async function reloadSession(broadcast = true) {
    try {
      const res = await fetch('/api/me', { cache: 'no-store' });
      const data = await res.json();
      setRecoveryCode(data.recovery_code);
      setSessionVersion((v) => v + 1);
      setSessionStatus('ready');
      if (broadcast && channelRef.current) {
        channelRef.current.postMessage({ type: 'SESSION_CHANGED' });
      }
      const directId = taskIdFromPath();
      if (directId) {
        void openTaskOrTheory(directId, false);
      } else {
        void loadCatalogue();
      }
    } catch {
      setSessionStatus('error');
    }
  }

  async function loadCatalogue() {
    setError(null);
    try {
      const list = await api.getTasks();
      setTasks(list);
      return list;
    } catch (e: any) {
      setError(e.message);
      return [];
    }
  }

  async function openTaskOrTheory(taskId: string, forceNew = false) {
    if (sessionStatus !== 'ready') return;
    setError(null);
    let currentTasks = tasks;
    if (currentTasks.length === 0) {
      currentTasks = await loadCatalogue();
    }
    const found = currentTasks.find((t) => t.id === taskId);
    if (found && (found.kind === 'theory' || found.kind === 'material')) {
      setActiveTheory(found);
      setAttempt(null);
      history.pushState(null, '', `/task/${taskId}`);
      return;
    }

    try {
      const att = await api.createAttempt(taskId, undefined, forceNew);
      setAttempt(att);
      setActiveTheory(null);
      history.pushState(null, '', `/task/${taskId}`);
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function handleRestoreKey(e: React.FormEvent) {
    e.preventDefault();
    const clean = restoreInput.trim().toLowerCase();
    if (!/^[0-9a-f]{32}$/.test(clean)) {
      setRestoreMsg('Ключ должен состоять ровно из 32 шестнадцатеричных символов (0-9, a-f).');
      return;
    }

    setSessionStatus('switching');
    try {
      const res = await fetch('/api/restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: clean })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail?.message || 'Не удалось восстановить ключ');

      setRestoreMsg('Ключ восстановлен. Переключение сессии...');
      setRestoreInput('');
      setKeyPanelOpen(false);
      await reloadSession(true);
    } catch (err: any) {
      setSessionStatus('ready');
      setRestoreMsg(`Ошибка: ${err.message}`);
    }
  }

  function backToCatalogue() {
    setAttempt(null);
    setActiveTheory(null);
    setViewAdmin(false);
    history.pushState(null, '', '/');
    void loadCatalogue();
  }

  // Каталог с группировкой
  const groupedCategories = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    const filtered = tasks.filter((t) => {
      const matchesSearch = !q || t.title?.toLowerCase().includes(q) || t.id.toLowerCase().includes(q);
      const cls = t.tags?.class || [];
      const matchesClass = selectedClass === null || (Array.isArray(cls) ? cls.includes(selectedClass) : cls === selectedClass);
      return matchesSearch && matchesClass;
    });

    const groups: Record<string, TaskManifest[]> = {};
    filtered.forEach((t) => {
      let cat = t.tags?.category?.trim() || (t.kind === 'theory' ? 'Справочные материалы' : 'Интерактивные практикумы');
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(t);
    });

    return Object.entries(groups).sort(([a], [b]) => {
      const ia = categoryOrder.indexOf(a);
      const ib = categoryOrder.indexOf(b);
      if (ia !== -1 && ib !== -1) return ia - ib;
      if (ia !== -1) return -1;
      if (ib !== -1) return 1;
      return a.localeCompare(b, 'ru');
    });
  }, [tasks, searchQuery, selectedClass, categoryOrder]);

  if (sessionStatus === 'loading' || sessionStatus === 'switching') {
    return (
      <div style={{ maxWidth: 600, margin: '120px auto', textAlign: 'center', fontFamily: 'sans-serif' }}>
        <h2>Синхронизация сессии...</h2>
        <p style={{ color: '#64748b' }}>Проверяем ключ доступа и настройки попыток</p>
      </div>
    );
  }

  if (viewAdmin) {
    return <AdminPanel onBack={backToCatalogue} />;
  }

  return (
    <div style={{ maxWidth: '1240px', margin: '0 auto', padding: '20px', fontFamily: 'sans-serif' }}>
      <nav style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', borderBottom: '1px solid #eee', paddingBottom: '10px' }}>
        <button onClick={backToCatalogue} style={{ background: 'none', border: 'none', color: '#0066cc', cursor: 'pointer', fontSize: '16px', fontWeight: 600 }}>
          {attempt || activeTheory ? '← Вернуться в каталог' : '⭐ Astrosite Каталог'}
        </button>

        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <button onClick={() => { setViewAdmin(true); history.pushState(null, '', '/admin'); }} style={{ padding: '6px 12px', background: '#f7fafc', border: '1px solid #cbd5e0', borderRadius: 4, cursor: 'pointer', fontSize: '13px' }}>
            ⚙ Админка
          </button>

          <div style={{ position: 'relative' }}>
            <button onClick={() => setKeyPanelOpen(!keyPanelOpen)} style={{ padding: '6px 12px', background: '#edf2f7', border: '1px solid #cbd5e0', borderRadius: 4, cursor: 'pointer', fontSize: '13px' }}>
              Ключ: <code>{recoveryCode ? `${recoveryCode.slice(0, 8)}…` : '—'}</code>
            </button>

            {keyPanelOpen && (
              <div style={{ position: 'absolute', right: 0, top: 35, width: 340, background: '#fff', border: '1px solid #cbd5e0', borderRadius: 6, padding: 16, boxShadow: '0 4px 12px rgba(0,0,0,0.15)', zIndex: 100 }}>
                <h4 style={{ margin: '0 0 6px 0' }}>Ваш ключ сессии:</h4>
                <div style={{ background: '#f7fafc', padding: 8, borderRadius: 4, fontFamily: 'monospace', fontSize: '12px', wordBreak: 'break-all', border: '1px dashed #a0aec0', marginBottom: 12 }}>
                  {recoveryCode}
                </div>
                <form onSubmit={handleRestoreKey}>
                  <input
                    type="text"
                    placeholder="Вставьте 32-значный hex-код"
                    value={restoreInput}
                    onChange={(e) => setRestoreInput(e.target.value)}
                    style={{ width: '100%', padding: '6px 8px', boxSizing: 'border-box', marginBottom: 8, borderRadius: 4, border: '1px solid #ccc' }}
                  />
                  <button type="submit" style={{ width: '100%', padding: '6px', background: '#2b6cb0', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}>
                    Восстановить сессию
                  </button>
                </form>
                {restoreMsg && <p style={{ fontSize: 12, marginTop: 8, color: '#2b6cb0' }}>{restoreMsg}</p>}
              </div>
            )}
          </div>
        </div>
      </nav>

      {error && <div style={{ padding: '12px', background: '#ffe6e6', color: '#cc0000', borderRadius: '4px', marginBottom: '16px' }}>{error}</div>}

      {/* Режим Теории */}
      {activeTheory && (
        <main style={{ background: '#fff', borderRadius: 8, border: '1px solid #e2e8f0', padding: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <div>
              <span style={{ fontSize: 12, background: '#ecfdf5', color: '#047857', padding: '3px 8px', borderRadius: 4, fontWeight: 700 }}>Теория</span>
              <h2 style={{ margin: '6px 0 2px 0' }}>{activeTheory.title}</h2>
            </div>
            <button onClick={backToCatalogue} style={{ padding: '6px 14px', background: '#3182ce', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}>В каталог</button>
          </div>
          <iframe
            src={`/static/tasks/${activeTheory.id}/${activeTheory.entry_point || 'widget.html'}`}
            sandbox="allow-scripts allow-same-origin"
            style={{ width: '100%', height: 'calc(100vh - 210px)', border: 'none' }}
            title={activeTheory.title}
          />
        </main>
      )}

      {/* Режим Задачи */}
      {!activeTheory && attempt && (
        <Workbench
          key={`${attempt.attempt_id}_${sessionVersion}`}
          attempt={attempt}
          confirmedCode={recoveryCode || ''}
          sessionVersion={sessionVersion}
          onNew={(id) => void openTaskOrTheory(id, true)}
        />
      )}

      {/* Режим Каталога */}
      {!activeTheory && !attempt && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 20 }}>
            <input
              type="text"
              placeholder="Поиск заданий..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{ padding: '8px 12px', borderRadius: 6, border: '1px solid #cbd5e0', minWidth: 260 }}
            />
            <div style={{ display: 'flex', border: '1px solid #cbd5e0', borderRadius: 6, overflow: 'hidden' }}>
              <button onClick={() => setSelectedClass(null)} style={{ padding: '7px 12px', border: 'none', background: selectedClass === null ? '#3182ce' : '#fff', color: selectedClass === null ? '#fff' : '#000', cursor: 'pointer' }}>Все</button>
              {[9, 10, 11].map((cls) => (
                <button key={cls} onClick={() => setSelectedClass(selectedClass === cls ? null : cls)} style={{ padding: '7px 12px', border: 'none', background: selectedClass === cls ? '#3182ce' : '#fff', color: selectedClass === cls ? '#fff' : '#000', cursor: 'pointer' }}>{cls} кл.</button>
              ))}
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            {groupedCategories.map(([catName, items]) => (
              <details key={catName} open style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8 }}>
                <summary style={{ padding: '14px 18px', background: '#f8fafc', cursor: 'pointer', fontWeight: 700 }}>{catName} ({items.length})</summary>
                <div style={{ padding: 16, display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 16 }}>
                  {items.map((t) => (
                    <div key={t.id} style={{ border: '1px solid #e2e8f0', borderRadius: 8, padding: 16, display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                      <div>
                        <h3 style={{ margin: '0 0 6px 0', fontSize: 16 }}>{t.title}</h3>
                        <p style={{ fontSize: 12, color: '#718096', margin: 0 }}>ID: {t.id}</p>
                      </div>
                      <button onClick={() => void openTaskOrTheory(t.id)} style={{ marginTop: 12, padding: '8px', background: '#3182ce', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}>
                        {t.kind === 'theory' ? 'Читать справку' : 'Решать →'}
                      </button>
                    </div>
                  ))}
                </div>
              </details>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}