import { Button, EmptyState, Panel } from "sculptor-ui";

export const NoResults = () => (
  <Panel>
    <EmptyState
      title="Записей нет"
      text="Под выбранные условия ничего не подошло."
      action={<Button href="#">Сбросить фильтры</Button>}
    />
  </Panel>
);

export const JournalStart = () => (
  <Panel title="последние входы">
    <EmptyState text="Журнал входов ведётся с этой версии — записей пока нет." />
  </Panel>
);
