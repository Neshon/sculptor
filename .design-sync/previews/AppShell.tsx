import { AppShell, Button, DataTable, PageHeader, Pager, Panel, SearchField, Toolbar } from "sculptor-ui";

export const ComponentLibrary = () => (
  <AppShell
    version="0.3.0"
    user="ivanova"
    nav={[
      {
        title: "Серверы",
        items: [
          { label: "SERVERS", title: "Серверы" },
          { label: "BOARDS", title: "Платы" },
          { label: "CHANGES", title: "Журнал изменений" },
        ],
      },
      {
        title: "Группы компонентов",
        items: [
          { label: "CAPACITOR", title: "Конденсаторы" },
          { label: "CONNECTOR", title: "Разъёмы" },
          { label: "RESISTOR", title: "Резисторы", active: true },
          { label: "TRANSISTOR", title: "Транзисторы" },
        ],
      },
    ]}
  >
    <PageHeader
      eyebrow="библиотека компонентов"
      title="Резисторы"
      count="1 433 записи"
      actions={<Button href="#" variant="primary">Добавить компонент</Button>}
    />
    <Panel>
      <Toolbar>
        <SearchField title="PN, описание, производитель" />
      </Toolbar>
      <DataTable
        flow
        rowHref={(_, index) => `#row-${index}`}
        columns={[
          { key: "pn", label: "Vendor PN", kind: "pn" },
          { key: "oyId", label: "OY ID", kind: "pn" },
          { key: "description", label: "Description", kind: "desc" },
          { key: "vendor", label: "Vendor", kind: "desc" },
        ]}
        rows={[
          { pn: "RC0402FR-07110KL", oyId: "ID_R_001435", description: "Chip Resistor, 0402, 110 kOhm, ±1%, 1/16W", vendor: "Yageo" },
          { pn: "RC0402FR-0710KL", oyId: "ID_R_001433", description: "Chip Resistor, 0402, 10 kOhm, ±1%, 1/16W", vendor: "Yageo" },
          { pn: "P1-12-0,062-330 Ом±5%", oyId: "ID_R_001434", description: "Chip Resistor, 0603, 330 Ohm, ±5%, 1/10W", vendor: "Эрзон" },
        ]}
      />
      <Pager page={1} pages={58} total={1433} />
    </Panel>
  </AppShell>
);
