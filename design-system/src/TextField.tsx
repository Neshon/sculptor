import type { ChangeEventHandler, ReactNode } from "react";
import { cx } from "./cx";

export interface TextFieldProps {
  /** Подпись над полем — мелкие прописные. */
  label?: ReactNode;
  name?: string;
  value?: string;
  defaultValue?: string;
  placeholder?: string;
  /** Звёздочка у подписи: поле обязательно. */
  required?: boolean;
  /** Многострочное поле (описание, примечание). */
  multiline?: boolean;
  /** Строк у многострочного поля. */
  rows?: number;
  /** Поле заполняет система — видно, но не правится (OY ID, группа). */
  locked?: boolean;
  /** Текст ошибки под полем; поле обводится красным. */
  error?: ReactNode;
  /** Подсказка под полем. */
  hint?: ReactNode;
  /** Растянуть поле на всю ширину `FormGrid`. */
  wide?: boolean;
  type?: "text" | "number" | "email" | "url" | "password" | "date";
  onChange?: ChangeEventHandler<HTMLInputElement | HTMLTextAreaElement>;
}

/**
 * Поле формы с подписью, подсказкой и ошибкой — как в формах сайта.
 * Значение набирается моноширинным: в формах Sculptor это данные.
 */
export function TextField({
  label, name, value, defaultValue, placeholder, required, multiline,
  rows = 3, locked, error, hint, wide, type = "text", onChange,
}: TextFieldProps) {
  const control = multiline ? (
    <textarea className={cx("field", "field--area", locked && "field--locked")}
              name={name} value={value} defaultValue={defaultValue}
              placeholder={placeholder} rows={rows} disabled={locked}
              onChange={onChange} />
  ) : (
    <input className={cx("field", locked && "field--locked")} type={type}
           name={name} value={value} defaultValue={defaultValue}
           placeholder={placeholder} disabled={locked} onChange={onChange} />
  );
  return (
    <div className={cx("formrow", error != null && "has-error", wide && "formrow--wide")}>
      {label != null && (
        <label>
          {label}
          {required && <span className="req" title="Обязательное поле">*</span>}
        </label>
      )}
      {control}
      {error != null && <div className="errors">{error}</div>}
      {hint != null && <div className="hint">{hint}</div>}
    </div>
  );
}
