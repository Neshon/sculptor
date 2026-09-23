import type { ReactNode } from "react";
import { cx } from "./cx";

export interface DataTableColumn {
  /** Ключ значения в строке. */
  key: string;
  /** Заголовок колонки. */
  label: ReactNode;
  /** `pn` — артикулы и коды; `num` — числа вправо; `desc` — текст, даты, имена. */
  kind?: "pn" | "num" | "desc";
  /** Ширина колонки, например `120` или `"20%"`. */
  width?: number | string;
}

export type DataTableRow = Record<string, ReactNode>;

export interface DataTableProps {
  columns: DataTableColumn[];
  rows: DataTableRow[];
  /**
   * Адрес строки: вся строка становится ссылкой, а значение первой колонки
   * — выделенной ссылкой.
   */
  rowHref?: (row: DataTableRow, index: number) => string | undefined;
  /** Таблица-отчёт без своей прокрутки: читается вместе со страницей. */
  flow?: boolean;
  /** Плотные строки — для длинных списков. */
  compact?: boolean;
}

/**
 * Таблица данных Sculptor: липкая шапка, подсветка строки при наведении,
 * артикулы моноширинным. Кладите внутрь `Panel`, фильтры — `Toolbar` над ней.
 */
export function DataTable({ columns, rows, rowHref, flow, compact }: DataTableProps) {
  return (
    <div className={cx("table-wrap", flow && "table-wrap--flow")}>
      <table className={cx("grid", compact && "grid--compact")}>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}
                  style={column.width != null ? { width: column.width } : undefined}>
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const href = rowHref?.(row, index);
            return (
              <tr key={index} data-href={href}>
                {columns.map((column, position) => (
                  <td key={column.key} className={column.kind}>
                    {href && position === 0
                      ? <a className="rowlink" href={href}>{row[column.key]}</a>
                      : row[column.key]}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
