import { Button, Chip, PageHeader } from "sculptor-ui";

export const ListPage = () => (
  <PageHeader
    eyebrow="библиотека компонентов"
    title="Резисторы"
    count="1 433 записи"
    actions={
      <>
        <Button href="#">Выгрузить CSV</Button>
        <Button href="#" variant="primary">Добавить компонент</Button>
      </>
    }
  />
);

export const ComponentCard = () => (
  <PageHeader
    eyebrow={<><a href="#">RESISTOR</a> · Резисторы</>}
    title="RC0402FR-07110KL"
    mono
    chips={<Chip tone="table">ID_R_001435</Chip>}
    actions={
      <>
        <Button href="#">Редактировать</Button>
        <Button href="#" variant="primary">Добавить по образцу</Button>
        <Button href="#" variant="danger">Удалить</Button>
      </>
    }
  />
);

export const BoardRevision = () => (
  <PageHeader
    eyebrow={<><a href="#">Платы</a> · <a href="#">HSBP-4L01</a> · ревизия</>}
    title="HSBP-4L01-02C"
    mono
    chips={
      <>
        <Chip tone="table">Rev 0.2</Chip>
        <Chip tone="table">BOM C</Chip>
        <Chip tone="replacement">не текущая ревизия</Chip>
      </>
    }
    count="66 позиций · 139 строк"
    actions={<Button href="#" variant="primary">Состав BOM</Button>}
  />
);
