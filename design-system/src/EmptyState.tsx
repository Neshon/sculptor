import type { ReactNode } from "react";

export interface EmptyStateProps {
  /** Что случилось: «Записей нет». */
  title?: ReactNode;
  /** Почему и что делать — приглушённым текстом. */
  text?: ReactNode;
  /** Действие — обычно `Button` («Сбросить фильтры»). */
  action?: ReactNode;
}

/** Пустой список или результат поиска — по центру панели, вместо таблицы. */
export function EmptyState({ title, text, action }: EmptyStateProps) {
  return (
    <div className="empty">
      {title != null && <h2>{title}</h2>}
      {text != null && <p className="muted">{text}</p>}
      {action}
    </div>
  );
}
