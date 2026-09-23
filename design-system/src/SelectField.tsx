import type { ChangeEventHandler, ReactNode } from "react";
import { cx } from "./cx";

export interface SelectOption {
  value: string;
  label?: string;
}

export interface SelectFieldProps {
  /** Подпись над полем. Без неё — голый список, например фильтр в `Toolbar`. */
  label?: ReactNode;
  name?: string;
  options: SelectOption[];
  value?: string;
  defaultValue?: string;
  /** Первый пункт без значения: «—» в форме или имя фильтра в `Toolbar`. */
  placeholder?: string;
  required?: boolean;
  error?: ReactNode;
  hint?: ReactNode;
  wide?: boolean;
  onChange?: ChangeEventHandler<HTMLSelectElement>;
}

/**
 * Выпадающий список: значение из справочника (SMT/THT, страна, подгруппа).
 * С подписью — поле формы; без подписи — фильтр над таблицей.
 */
export function SelectField({
  label, name, options, value, defaultValue, placeholder, required, error,
  hint, wide, onChange,
}: SelectFieldProps) {
  const select = (
    <select className="field field--select" name={name} value={value}
            defaultValue={defaultValue} onChange={onChange}>
      {placeholder != null && <option value="">{placeholder}</option>}
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label ?? option.value}
        </option>
      ))}
    </select>
  );
  if (label == null) return select;
  return (
    <div className={cx("formrow", error != null && "has-error", wide && "formrow--wide")}>
      <label>
        {label}
        {required && <span className="req" title="Обязательное поле">*</span>}
      </label>
      {select}
      {error != null && <div className="errors">{error}</div>}
      {hint != null && <div className="hint">{hint}</div>}
    </div>
  );
}
