import { Chip } from "sculptor-ui";

export const Tones = () => (
  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
    <Chip>не утверждена</Chip>
    <Chip tone="table">Rev 0.2</Chip>
    <Chip tone="replacement">замена</Chip>
    <Chip tone="added">да</Chip>
    <Chip tone="edited">в работе</Chip>
    <Chip tone="gone">отключён</Chip>
    <Chip tone="dup">администратор</Chip>
  </div>
);

export const JournalEvents = () => (
  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
    <Chip tone="added" event>добавлен</Chip>
    <Chip tone="edited" event>изменён</Chip>
    <Chip tone="gone" event>удалён</Chip>
    <Chip tone="dup" event>дубль</Chip>
    <Chip tone="image" event>изображение</Chip>
  </div>
);
