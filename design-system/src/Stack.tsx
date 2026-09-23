import type { ReactNode } from "react";

export interface StackProps {
  children?: ReactNode;
}

/** Колонка блоков (обычно `Panel`) с одинаковым просветом между ними. */
export function Stack({ children }: StackProps) {
  return <div className="stack">{children}</div>;
}
