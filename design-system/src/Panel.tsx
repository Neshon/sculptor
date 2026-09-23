import type { CSSProperties, ReactNode } from "react";

export interface PanelProps {
  /** Заголовок блока — мелкие прописные над содержимым («сотрудник», «роли и права»). */
  title?: ReactNode;
  /** Справа в заголовке — ссылка или метка («все 73 записи»). */
  aside?: ReactNode;
  /** Отступы для свободного текста; у `Specs`, `DataTable`, `FormGrid` свои. */
  padded?: boolean;
  children?: ReactNode;
}

const PADDED: CSSProperties = { padding: "var(--s-4) var(--s-5)" };

/**
 * Панель — белая карточка со скруглением и тонким контуром. Основной
 * строительный блок страниц: в ней таблицы, списки сведений, формы.
 *
 * У самой панели внутренних отступов нет — их дают вложенные блоки
 * (`Specs`, `DataTable`, `FormGrid`, `EmptyState`, `Toolbar`). Для
 * свободного текста включите `padded`.
 */
export function Panel({ title, aside, padded, children }: PanelProps) {
  return (
    <div className="panel">
      {title != null && (
        <div className="section__head">
          {title}
          {aside != null && <><span className="toolbar__spacer" />{aside}</>}
        </div>
      )}
      {padded ? <div style={PADDED}>{children}</div> : children}
    </div>
  );
}
