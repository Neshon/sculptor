import { Panel, Specs, Stack } from "sculptor-ui";

export const PanelsColumn = () => (
  <Stack>
    <Panel title="сотрудник">
      <Specs
        items={[
          { label: "Логин", value: "ivanova" },
          { label: "Отдел", value: "Конструкторский отдел" },
        ]}
      />
    </Panel>
    <Panel title="последние входы">
      <Specs
        layout="tight"
        items={[
          { label: "23.09.2026 13:59", value: "10.1.2.3" },
          { label: "22.09.2026 09:12", value: "10.1.2.3" },
        ]}
      />
    </Panel>
  </Stack>
);
