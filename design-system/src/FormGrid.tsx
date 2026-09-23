import type { ReactNode } from "react";

export interface FormGridProps {
  /** Сколько полей в ряд: 3 — как в форме компонента, 2 — как в форме платы, 1 — узкая форма. */
  columns?: 1 | 2 | 3;
  /** Поля — `TextField` и `SelectField`. */
  children?: ReactNode;
}

/**
 * Сетка полей формы с отступами внутри `Panel`. Под ней — `FormBar`
 * с кнопками сохранения.
 */
export function FormGrid({ columns = 3, children }: FormGridProps) {
  return (
    <div className="formgrid"
         style={columns === 3 ? undefined
                              : { gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>
      {children}
    </div>
  );
}

export interface FormBarProps {
  /** Кнопки: главная `Button variant="primary"` первой, «Отмена» — `variant="ghost"`. */
  children?: ReactNode;
}

/** Нижняя полоса формы с кнопками; прилипает к низу экрана при прокрутке длинной формы. */
export function FormBar({ children }: FormBarProps) {
  return <div className="formbar">{children}</div>;
}
