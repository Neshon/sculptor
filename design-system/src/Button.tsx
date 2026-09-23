import type { MouseEventHandler, ReactNode } from "react";
import { cx } from "./cx";

export interface ButtonProps {
  /** Вид кнопки — когда какой, см. описание компонента. */
  variant?: "default" | "primary" | "danger" | "ghost" | "reset";
  /** Уменьшенная кнопка — для строк таблицы и тесных мест. */
  small?: boolean;
  /** Если задан — рисуется ссылкой `<a>` того же вида. */
  href?: string;
  type?: "button" | "submit" | "reset";
  disabled?: boolean;
  title?: string;
  onClick?: MouseEventHandler<HTMLElement>;
  children?: ReactNode;
}

/**
 * Кнопка Sculptor: скруглённая «таблетка», акцент — фирменный фиолетовый.
 * Со ссылкой (`href`) выглядит так же, как кнопка.
 *
 * Виды: `primary` — главное действие экрана, одна на экран; `default` —
 * обычное действие; `ghost` — второстепенное рядом с главным («Отмена»);
 * `danger` — только безвозвратное (удаление); `reset` — «Сбросить» над
 * фильтрами, когда что-то отфильтровано.
 */
export function Button({
  variant = "default", small, href, type = "button", disabled, title,
  onClick, children,
}: ButtonProps) {
  const className = cx("btn", variant !== "default" && `btn--${variant}`,
                       small && "btn--small");
  if (href !== undefined) {
    return (
      <a className={className} href={disabled ? undefined : href}
         aria-disabled={disabled || undefined} title={title} onClick={onClick}>
        {children}
      </a>
    );
  }
  return (
    <button className={className} type={type} disabled={disabled}
            title={title} onClick={onClick}>
      {children}
    </button>
  );
}
