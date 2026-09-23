import { Panel, SearchField, Toolbar } from "sculptor-ui";

export const InToolbar = () => (
  <Panel>
    <Toolbar>
      <SearchField title="PN, описание, производитель" />
    </Toolbar>
  </Panel>
);

export const WithQuery = () => (
  <Panel>
    <Toolbar>
      <SearchField defaultValue="GRM188" placeholder="Поиск по списку" />
    </Toolbar>
  </Panel>
);
