import { useEffect, useRef, useState } from 'react';

export interface ProgressSession { userId: number; revision: number }
interface TaskProgress { status: 'solved' | 'submitted_ungraded'; best_score: number | null }
interface Progress {
  user_id: number;
  summary: { solved_tasks: number; available_tasks: number; total_score: number };
  tasks: Record<string, TaskProgress>;
}
const scoreFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 10 });
export const formatScore = (score: number) => scoreFormat.format(score);

export function useCatalogueProgress(session: ProgressSession | null, open: boolean, refresh: number) {
  const [retry, setRetry] = useState(0);
  const [result, setResult] = useState<{
    session: ProgressSession; refresh: number; retry: number; data?: Progress; error?: boolean;
  } | null>(null);
  const currentSession = useRef(session);
  currentSession.current = session;
  useEffect(() => {
    if (!session || !open) return;
    const controller = new AbortController();
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch('/api/me/progress', { cache: 'no-store', signal: controller.signal });
        if (!response.ok) throw new Error('Progress unavailable');
        const data: Progress = await response.json();
        if (data.user_id !== session.userId) throw new Error('Session mismatch');
        if (!cancelled && currentSession.current === session) setResult({ session, refresh, retry, data });
      } catch {
        if (!cancelled && currentSession.current === session) setResult({ session, refresh, retry, error: true });
      }
    })();
    return () => { cancelled = true; controller.abort(); };
  }, [session, open, refresh, retry]);
  const visible = open && result?.session === session && result?.refresh === refresh && result?.retry === retry
    ? result : null;
  return { data: visible?.data, error: visible?.error, retry: () => setRetry(n => n + 1) };
}

export function ProgressSummary({ progress }: { progress: ReturnType<typeof useCatalogueProgress> }) {
  const summary = progress.data?.summary;
  return <section className="progress-summary" aria-label="Ваш прогресс" aria-live="polite">
    <h2>Ваш прогресс</h2>
    {progress.error ? <p>Не удалось загрузить прогресс <button onClick={progress.retry}>Повторить</button></p>
      : !summary ? <p role="status">Загрузка прогресса…</p>
      : summary.available_tasks === 0 ? <p>Пока нет доступных задач</p>
      : <p>Решено: <strong>{summary.solved_tasks} из {summary.available_tasks} задач</strong>
        {' · '}Всего баллов: <strong>{formatScore(summary.total_score)}</strong></p>}
    <p className="muted">Учитывается лучший результат по каждой задаче.</p>
  </section>;
}

export function ProgressBadge({ task }: { task?: TaskProgress }) {
  if (!task) return null;
  return <p className={`progress-badge progress-${task.status}`}>
    {task.status === 'solved'
      ? `Решено · лучший результат: ${formatScore(task.best_score!)} баллов`
      : 'Сдано — оценка недоступна'}
  </p>;
}
