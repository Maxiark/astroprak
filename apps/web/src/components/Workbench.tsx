// apps/web/src/components/Workbench.tsx
import { useEffect, useRef, useState, useMemo } from 'react';
import { api, type Attempt } from '../api';
import { TaskErrorBoundary } from './TaskErrorBoundary';
import { useFrameTheme } from '../frameTheme';
import { EventQueue } from '../events';

export function Workbench({ 
  attempt, 
  confirmedCode,
  sessionVersion,
  onNew 
}: { 
  attempt: Attempt; 
  confirmedCode: string;
  sessionVersion: number;
  onNew: (taskId: string) => void;
}) {
  const task = attempt.task;
  const events = useMemo(() => new EventQueue(attempt.attempt_id), [attempt.attempt_id]);
  useEffect(() => () => { void events.flush(); }, [events]);

  const [values, setValues] = useState<Record<string, any>>(attempt.answers ?? {});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitted, setIsSubmitted] = useState(attempt.submitted || false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [iframeHeight, setIframeHeight] = useState<number>(860);

  const submissionConflictRef = useRef(false);
  const [submissionConflict, setSubmissionConflict] = useState(false);

  const iframeRef = useRef<HTMLIFrameElement>(null);
  useFrameTheme(iframeRef, task.id);
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Изоляция драфта в localStorage по ключу сессии и попытки
  const draftStorageKey = `draft_${confirmedCode}_${attempt.attempt_id}`;

  const scheduleDraftSave = (nextValues: Record<string, any>) => {
    if (isSubmitted || submissionConflictRef.current) return;
    setSaveStatus('saving');
    localStorage.setItem(draftStorageKey, JSON.stringify(nextValues));

    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    saveTimeoutRef.current = setTimeout(async () => {
      if (submissionConflictRef.current) return;
      try {
        const res = await fetch(`/api/attempts/${attempt.attempt_id}/answers`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ answers: nextValues })
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          if (errData?.detail?.code === 'ATTEMPT_ALREADY_SUBMITTED') {
            submissionConflictRef.current = true;
            setSubmissionConflict(true);
            if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
            setError('Работа уже сдана. Обновите страницу, чтобы увидеть принятый результат');
          } else if (!submissionConflictRef.current && errData?.detail?.code === 'SESSION_MISMATCH') {
            setError('Сессия в браузере была переключена. Сохранение в чужую попытку заблокировано.');
          }
          setSaveStatus('error');
        } else if (!submissionConflictRef.current) {
          setSaveStatus('saved');
        }
      } catch {
        setSaveStatus('error');
      }
    }, 350);
  };

  async function submitAttempt(finalAnswers?: Record<string, any>) {
    if (isSubmitted || busy || submissionConflictRef.current) return;
    setBusy(true);
    setError(null);
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);

    const answersToSend = finalAnswers ? { ...values, ...finalAnswers } : values;

    try {
      await events.flush();
      const res = await api.submit(attempt.attempt_id, answersToSend);
      if (submissionConflictRef.current) return;
      setIsSubmitted(true);
      setValues(res.answers);
      setSaveStatus('saved');

      // Передаём подтверждённый сервером recovery_code
      if (iframeRef.current?.contentWindow) {
        iframeRef.current.contentWindow.postMessage({
          type: 'ASTROSITE_SUBMIT_SUCCESS',
          attempt_id: res?.attempt_id,
          recovery_code: res?.recovery_code || confirmedCode,
          score: res?.score,
          max_score: res?.max_score,
          grading: res?.grading || (res?.score !== undefined ? { score: res.score, max_score: res.max_score } : null)
        }, window.location.origin);
      }
    } catch (e: any) {
      if (submissionConflictRef.current) return;
      const msg = e.message || 'Ошибка сдачи работы';
      setError(msg);
      if (iframeRef.current?.contentWindow) {
        iframeRef.current.contentWindow.postMessage({
          type: 'ASTROSITE_SUBMIT_ERROR',
          error: msg
        }, window.location.origin);
      }
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      if (iframeRef.current && event.source !== iframeRef.current.contentWindow) return;
      if (!event.data || typeof event.data !== 'object') return;

      if (event.data.type === 'ASTROSITE_FRAME_RESIZE') {
        const h = Math.ceil(Number(event.data.height));
        if (h && h > 150 && h < 25000) {
          setIframeHeight((prev) => (Math.abs(h + 32 - prev) > 4 ? h + 32 : prev));
        }
      }

      if (event.data.type === 'ASTROSITE_EVENT') {
        const evName = typeof event.data.name === 'string' ? event.data.name : 'widget.action';
        const evPayload = (event.data.payload && typeof event.data.payload === 'object') ? event.data.payload : {};
        events.push(evName, evPayload);
      }

      if (event.data.type === 'ASTROSITE_ANSWER_CHANGE') {
        if (isSubmitted || submissionConflictRef.current) return;
        const incoming = event.data.answers;
        if (incoming && typeof incoming === 'object') {
          setValues((prev) => {
            const merged = { ...prev, ...incoming };
            scheduleDraftSave(merged);
            return merged;
          });
        }
      }

      if (event.data.type === 'ASTROSITE_SUBMIT_ATTEMPT') {
        void submitAttempt(event.data.answers);
      }
    };

    window.addEventListener('message', handleMessage);
    return () => {
      window.removeEventListener('message', handleMessage);
      if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    };
  }, [attempt.attempt_id, values, isSubmitted]);

  const handleIframeLoad = () => {
    iframeRef.current?.contentWindow?.postMessage({
      type: 'ASTROSITE_INIT_DATA',
      data: task.data,
      draft: values,
      session_code: confirmedCode,
      session_version: sessionVersion,
      is_submitted: isSubmitted,
      grading: attempt.grading || null,
      created_at: attempt.created_at || null
    }, window.location.origin);
  };

  return (
    <main className="workbench">
      <header className="workbench-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2>{task.title ?? 'Интерактивная задача'}</h2>
          <p className="muted">
            ID: {task.id} | Сессия: <code>{confirmedCode.slice(0, 8)}…</code> | Статус: {submissionConflict ? 'Требуется обновление страницы' : isSubmitted ? 'Сдано' : 'В процессе'}
            {saveStatus === 'saving' && ' · Сохранение...'}
            {saveStatus === 'saved' && !isSubmitted && ' · Черновик сохранён'}
            {saveStatus === 'error' && ' · Ошибка сохранения'}
          </p>
        </div>
        {isSubmitted && (
          <button onClick={() => onNew(task.id)} style={{ padding: '6px 12px', background: 'var(--color-primary)', color: 'var(--color-on-primary)', border: 'none', borderRadius: 4, cursor: 'pointer' }}>
            Новый вариант
          </button>
        )}
      </header>

      {error && <p className="error" role="alert" style={{ background: 'var(--color-error-bg)', color: 'var(--color-error-text)', padding: 10, borderRadius: 4 }}>{error}</p>}

      {!submissionConflict && <TaskErrorBoundary>
        <iframe
          ref={iframeRef}
          src={`/static/tasks/${task.id}/${task.entry_point || 'widget.html'}`}
          sandbox="allow-scripts allow-same-origin"
          className="task-iframe"
          onLoad={handleIframeLoad}
          style={{ width: '100%', height: `${iframeHeight}px`, border: 'none', borderRadius: 8, background: 'var(--color-surface)' }}
          title={task.title}
        />
      </TaskErrorBoundary>}
    </main>
  );
}