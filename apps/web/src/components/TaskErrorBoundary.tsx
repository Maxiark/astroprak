// Путь: apps/web/src/components/TaskErrorBoundary.tsx
import React, { Component, ErrorInfo, ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

export class TaskErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(_: Error): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Ошибка внутри контейнера задачи:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: '20px', background: 'var(--color-surface)5f5', border: '1px solid var(--color-error-text)', borderRadius: '8px' }}>
          <h3 style={{ color: 'var(--color-error-text)', marginTop: 0 }}>Не удалось отобразить интерактивный компонент этой задачи</h3>
          <p>В коде виджета произошла внутренняя ошибка. Ядро сайта продолжает работать.</p>
          <button onClick={() => window.location.reload()} className="submit small">
            Перезагрузить страницу
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
