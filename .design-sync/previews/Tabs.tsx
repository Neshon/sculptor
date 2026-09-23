import { DataTable, EmptyState, Specs, Tabs } from "sculptor-ui";

export const ComponentCard = () => (
  <Tabs
    tabs={[
      {
        label: "Параметры",
        note: "6",
        content: (
          <Specs
            items={[
              { label: "Value", value: "110 kOhm" },
              { label: "Tolerance", value: "±1%" },
              { label: "Power dissipation, W", value: "1/16" },
              { label: "Voltage, V", value: "50" },
              { label: "Temperature min, °C", value: "-55" },
              { label: "Temperature max, °C", value: "155" },
            ]}
          />
        ),
      },
      {
        label: "Аналоги",
        note: "2",
        content: (
          <DataTable
            flow
            columns={[
              { key: "pn", label: "Vendor PN", kind: "pn" },
              { key: "vendor", label: "Vendor", kind: "desc" },
            ]}
            rows={[
              { pn: "RC0402FR-07110KL", vendor: "Yageo" },
              { pn: "ERJ-2RKF1103X", vendor: "Panasonic" },
            ]}
          />
        ),
      },
      {
        label: "Применяемость",
        content: <EmptyState title="Не применяется" text="Компонент пока не стоит ни на одной плате." />,
      },
    ]}
  />
);

export const SecondTabOpen = () => (
  <Tabs
    defaultIndex={1}
    tabs={[
      { label: "Документы", content: <EmptyState text="Документов пока нет." /> },
      {
        label: "Чек-лист SMT",
        note: "4/9",
        content: (
          <Specs
            layout="tight"
            items={[
              { label: "Трафарет", value: "готов" },
              { label: "Программа установщика", value: "в работе" },
            ]}
          />
        ),
      },
    ]}
  />
);
