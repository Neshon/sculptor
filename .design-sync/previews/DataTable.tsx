import { Chip, DataTable, Panel } from "sculptor-ui";

export const ComponentList = () => (
  <Panel>
    <DataTable
      flow
      rowHref={(_, index) => `#row-${index}`}
      columns={[
        { key: "vendorPn", label: "Vendor PN", kind: "pn" },
        { key: "oyId", label: "OY ID", kind: "pn" },
        { key: "description", label: "Description", kind: "desc" },
        { key: "package", label: "Package", kind: "pn" },
      ]}
      rows={[
        { vendorPn: "RC0402FR-07110KL", oyId: "ID_R_001435", description: "Chip Resistor, 0402, 110 kOhm, ±1%, 1/16W", package: "0402" },
        { vendorPn: "P1-12-0,062-330 Ом±5%", oyId: "ID_R_001434", description: "Chip Resistor, 0603, 330 Ohm, ±5%, 1/10W", package: "0603" },
        { vendorPn: "GRM188R71H104KA93D", oyId: "ID_C_000221", description: "MLCC, 0603, 100 nF, 50V, X7R, ±10%", package: "0603" },
        { vendorPn: "CL05B104KO5NNNC", oyId: "ID_C_000222", description: "MLCC, 0402, 100 nF, 16V, X7R, ±10%", package: "0402" },
      ]}
    />
  </Panel>
);

export const ChangeLog = () => (
  <Panel title="мои правки в справочнике">
    <DataTable
      flow
      compact
      columns={[
        { key: "event", label: "Событие", width: 120 },
        { key: "when", label: "Дата изменения", kind: "desc", width: 150 },
        { key: "who", label: "Произвёл изменение", kind: "desc" },
        { key: "target", label: "Компонент", kind: "pn" },
        { key: "fields", label: "Строк", kind: "num", width: 80 },
      ]}
      rows={[
        { event: <Chip tone="added" event>добавлен</Chip>, when: "22.09.2026 17:04", who: "Библиотекарь Иванова", target: "CONNECTOR #504", fields: 9 },
        { event: <Chip tone="edited" event>изменён</Chip>, when: "21.09.2026 11:25", who: "Библиотекарь Иванова", target: "CAPACITOR #165", fields: 1 },
        { event: <Chip tone="gone" event>удалён</Chip>, when: "21.09.2026 13:56", who: "admin", target: "RESISTOR #1434", fields: 24 },
      ]}
    />
  </Panel>
);
