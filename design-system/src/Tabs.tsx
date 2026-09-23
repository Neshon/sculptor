import { useState, type ReactNode } from "react";
import { cx } from "./cx";

export interface TabItem {
  /** Название вкладки. */
  label: string;
  /** Число у названия — сколько записей внутри («3», «50+»). */
  note?: ReactNode;
  /** Содержимое — ложится в панель вкладки; `Specs`, `DataTable`, `EmptyState`. */
  content: ReactNode;
}

export interface TabsProps {
  tabs: TabItem[];
  /** Какая вкладка открыта сначала, с 0. */
  defaultIndex?: number;
}

/**
 * Вкладки над панелями — как в карточке компонента («Параметры»,
 * «Аналоги», «История», «Применяемость»). Каждая вкладка — своя панель.
 */
export function Tabs({ tabs, defaultIndex = 0 }: TabsProps) {
  const [active, setActive] = useState(defaultIndex);
  return (
    <div className="tabs">
      {tabs.length > 1 && (
        <div className="tabs__bar" role="tablist">
          {tabs.map((tab, index) => (
            <button key={tab.label} type="button" role="tab"
                    className={cx("tabs__btn", index === active && "is-active")}
                    aria-selected={index === active}
                    tabIndex={index === active ? 0 : -1}
                    onClick={() => setActive(index)}>
              {tab.label}
              {tab.note != null && <span className="tabs__note">{tab.note}</span>}
            </button>
          ))}
        </div>
      )}
      {tabs.map((tab, index) => (
        <div key={tab.label} className="panel" hidden={index !== active}>
          {tab.content}
        </div>
      ))}
    </div>
  );
}
