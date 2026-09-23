import type { ReactNode } from "react";
import { cx } from "./cx";

export interface AlertProps {
  /** `info` — пояснение (фиолетовая полоса слева); `error` — «Не сохранено» и список ошибок (красная). */
  tone?: "info" | "error";
  /** Короткий заголовок жирным: «Не сохранено.» */
  title?: ReactNode;
  /** Пункты списком — например, ошибки по полям. */
  items?: ReactNode[];
  children?: ReactNode;
}

/** Сообщение над формой или таблицей: полоса слева, текст и список пунктов. */
export function Alert({ tone = "info", title, items, children }: AlertProps) {
  return (
    <div className={cx("alert", tone === "error" && "alert--error")}
         role={tone === "error" ? "alert" : undefined}>
      {title != null && <b>{title}</b>}
      {title != null && children != null && " "}
      {children}
      {items && items.length > 0 && (
        <ul>{items.map((item, index) => <li key={index}>{item}</li>)}</ul>
      )}
    </div>
  );
}
