import type { ChangeEventHandler } from "react";

export interface SearchFieldProps {
  name?: string;
  value?: string;
  defaultValue?: string;
  /** По умолчанию «Поиск по списку». */
  placeholder?: string;
  /** Подсказка при наведении — по каким полям ищет. */
  title?: string;
  onChange?: ChangeEventHandler<HTMLInputElement>;
}

/** Поле поиска над таблицей, в `Toolbar` — первым элементом ряда. */
export function SearchField({
  name = "q", value, defaultValue, placeholder = "Поиск по списку", title,
  onChange,
}: SearchFieldProps) {
  return (
    <input className="field field--search" type="search" name={name}
           value={value} defaultValue={defaultValue} placeholder={placeholder}
           title={title} autoComplete="off" onChange={onChange} />
  );
}
