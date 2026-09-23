import { Button } from "sculptor-ui";

export const Variants = () => (
  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
    <Button variant="primary">Добавить компонент</Button>
    <Button>Редактировать</Button>
    <Button variant="ghost">Отмена</Button>
    <Button variant="danger">Удалить</Button>
    <Button variant="reset">Сбросить</Button>
  </div>
);

export const CardActions = () => (
  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
    <Button href="#">Редактировать</Button>
    <Button href="#">Добавить изображение</Button>
    <Button href="#" variant="primary">Добавить по образцу</Button>
    <Button href="#" variant="danger">Удалить</Button>
  </div>
);

export const SmallAndDisabled = () => (
  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
    <Button small>Выбрать</Button>
    <Button small variant="primary">Добавить</Button>
    <Button disabled>Сохранить</Button>
  </div>
);
