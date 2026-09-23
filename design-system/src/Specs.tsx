import type { ReactNode } from "react";
import { cx } from "./cx";

export interface SpecsItem {
  /** Подпись — мелкие прописные слева. */
  label: ReactNode;
  /** Значение — моноширинным справа; пустое показывайте как «—». */
  value: ReactNode;
}

export interface SpecsProps {
  items: SpecsItem[];
  /** `tight` — плотнее; `pairs` — плотнее и с узкой колонкой подписей (180 px). */
  layout?: "default" | "tight" | "pairs";
}

/**
 * Список сведений «подпись — значение»: карточка компонента, платы,
 * сотрудника. Кладите в `Panel` с заголовком.
 */
export function Specs({ items, layout = "default" }: SpecsProps) {
  return (
    <dl className={cx("specs", layout !== "default" && `specs--${layout}`)}>
      {items.map((item, index) => (
        <div key={index}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
