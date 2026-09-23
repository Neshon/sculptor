import type { ReactNode } from "react";

export interface PageHeaderProps {
  /** Раздел мелкими буквами над заголовком; может содержать ссылки-«хлебные крошки». */
  eyebrow?: ReactNode;
  /** Заголовок страницы (h1). */
  title: ReactNode;
  /** Набрать заголовок моноширинным — для артикулов и номеров плат. */
  mono?: boolean;
  /** Метки сразу за заголовком — обычно `Chip`. */
  chips?: ReactNode;
  /** Счётчик приглушённым текстом: «1 433 записи», «7 сотрудников». */
  count?: ReactNode;
  /** Кнопки справа — обычно `Button`; главная — `variant="primary"`. */
  actions?: ReactNode;
}

/**
 * Шапка страницы: раздел, заголовок, метки, счётчик и кнопки действий
 * справа. Каждая страница Sculptor начинается с неё.
 */
export function PageHeader({ eyebrow, title, mono, chips, count, actions }: PageHeaderProps) {
  return (
    <div className="legend">
      {eyebrow != null && <div className="legend__eyebrow">{eyebrow}</div>}
      <div className="legend__row">
        <h1 className={mono ? "mono" : undefined}>{title}</h1>
        {chips}
        {count != null && <span className="legend__count">{count}</span>}
        {actions != null && <span className="legend__actions">{actions}</span>}
      </div>
    </div>
  );
}
