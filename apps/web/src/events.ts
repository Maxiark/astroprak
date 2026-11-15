export class EventQueue {
  private attemptId: string;
  private queue: Array<{ name: string; payload: Record<string, any>; ts: number }> = [];

  constructor(attemptId: string) {
    this.attemptId = attemptId;
  }

  push(name: string, payload: Record<string, any> = {}) {
    this.queue.push({ name, payload, ts: Date.now() });
    if (this.queue.length >= 5) {
      void this.flush();
    }
  }

  async flush() {
    if (this.queue.length === 0) return;
    const items = [...this.queue];
    this.queue = [];

    try {
      await fetch(`/api/attempts/${encodeURIComponent(this.attemptId)}/events`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ events: items }),
      });
    } catch (e) {
      console.warn('Не удалось отправить события аналитики:', e);
    }
  }
}
