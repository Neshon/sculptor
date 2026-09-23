import type { ReactNode } from "react";

export interface ToolbarProps {
  /** Поля фильтров, поиск, кнопки — в ряд; `ToolbarSpacer` отодвигает остальное вправо. */
  children?: ReactNode;
}

/**
 * Ряд над таблицей внутри `Panel`: поиск, фильтры, «Сбросить», кнопки.
 * Отделён от содержимого панели тонкой линией.
 */
export function Toolbar({ children }: ToolbarProps) {
  return <div className="toolbar">{children}</div>;
}

/** Распорка в `Toolbar`: всё, что после неё, прижимается к правому краю. */
export function ToolbarSpacer() {
  return <span className="toolbar__spacer" />;
}
