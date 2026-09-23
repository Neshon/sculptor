import { Alert } from "sculptor-ui";

export const FormErrors = () => (
  <Alert
    tone="error"
    title="Не сохранено."
    items={[
      <a href="#">Vendor PN: заполните это поле — «---» и прочерки не годятся.</a>,
      <a href="#">OY PN: допустимы латинские буквы, цифры и знаки препинания.</a>,
    ]}
  />
);

export const Info = () => (
  <Alert title="Компонент стоит на платах.">
    Строки состава останутся, но потеряют связь с библиотекой.
  </Alert>
);
