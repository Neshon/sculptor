import { Button, Panel, SearchField, Toolbar, ToolbarSpacer } from "sculptor-ui";

export const PushRight = () => (
  <Panel>
    <Toolbar>
      <SearchField placeholder="Поиск по платам" />
      <ToolbarSpacer />
      <Button href="#">Загрузить BOM</Button>
      <Button href="#" variant="primary">Завести плату</Button>
    </Toolbar>
  </Panel>
);
