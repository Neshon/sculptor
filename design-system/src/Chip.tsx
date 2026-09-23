import type { ReactNode } from "react";
import { cx } from "./cx";

export interface ChipProps {
  /** Смысл и цвет метки — когда какой, см. описание компонента. */
  tone?: "default" | "table" | "replacement" | "added" | "edited" | "gone"
    | "dup" | "image";
  /** Компактная метка события в журналах (мельче, не переносится). */
  event?: boolean;
  title?: string;
  children?: ReactNode;
}

/**
 * Метка-«чип»: короткий статус рядом с заголовком или в ячейке таблицы.
 * Одно-два слова строчными — «добавлен», «замена», «нет».
 *
 * Тона: `default` — нейтральный статус («нет», «не утверждена»); `table` —
 * имя таблицы или ревизии («Rev 0.2»); `replacement` — «замена», залитая
 * фиолетовым; `added` — успех, «добавлен», «да»; `edited` — «изменён»;
 * `gone` — «удалён», ошибка; `dup` — фиолетовый акцент («дубль»,
 * «администратор»); `image` — нейтральное событие без правки данных.
 */
export function Chip({ tone = "default", event, title, children }: ChipProps) {
  return (
    <span className={cx("chip", tone !== "default" && `chip--${tone}`,
                        event && "chip--event")} title={title}>
      {children}
    </span>
  );
}
