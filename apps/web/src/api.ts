export interface FieldSpec {
  id: string;
  kind?: string;
  type?: string;
  label?: string;
  unit?: string;
  options?: string[];
  hint?: string;
}

export interface TaskManifest {
  id: string;
  title: string;
  kind?: 'generated' | 'archive' | 'theory' | 'material';
  version?: string;
  hidden?: boolean;
  tags?: {
    class?: number | number[];
    topic?: string;
    category?: string;
    category_order?: number;
    skills?: string[];
  };
  max_score?: number;
  entry_point?: string;
  generator_script?: string;
  schema?: {
    fields?: any[];
  };
  data?: Record<string, any>;
}

export interface Attempt {
  attempt_id: string;
  task: TaskManifest;
  answers?: Record<string, any>;
  submitted?: boolean;
  score?: number | null;
  grading?: Record<string, any> | null;
  created_at?: string | null;
}

export interface Family {
  id: string;
  title: string;
}

export const api = {
  async getTasks(): Promise<TaskManifest[]> {
    const res = await fetch('/api/tasks');
    if (!res.ok) throw new Error(`Ошибка загрузки каталога: ${res.statusText}`);
    const data = await res.json();
    return data.tasks ?? [];
  },

  async createAttempt(taskId: string, seed?: number, forceNew = false): Promise<Attempt> {
    const params = new URLSearchParams({ task_id: taskId });
    if (seed !== undefined) params.set('seed', String(seed));
    if (forceNew) params.set('new', 'true');

    const res = await fetch(`/api/attempts?${params.toString()}`, {
      method: 'POST',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Ошибка создания задания');
    }
    return res.json();
  },

  async submit(attemptId: string, answers: Record<string, any>): Promise<any> {
    const res = await fetch(`/api/attempts/${encodeURIComponent(attemptId)}/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answers }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Ошибка сдачи решения');
    }
    return res.json();
  },
};
