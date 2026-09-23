import type { ReactNode } from "react";

export interface ColumnsProps {
  /** `main` — левая колонка шире (≈1.4 : 1); `aside` — узкая левая под картинку. */
  layout?: "main" | "aside";
  children?: ReactNode;
}

/**
 * Две колонки на странице — например, сведения слева и история справа.
 * Кладите в каждую колонку `Stack` с панелями.
 *
 * На узком экране колонки встают друг под друга: `main` — уже 1080 px
 * окна, `aside` — уже 1100 px.
 */
export function Columns({ layout = "main", children }: ColumnsProps) {
  return (
    <div className={layout === "aside" ? "cols cols--aside" : "cols"}>
      {children}
    </div>
  );
}
