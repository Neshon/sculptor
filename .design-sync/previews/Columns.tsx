import { Chip, Columns, DataTable, Panel, Specs, Stack } from "sculptor-ui";

export const ProfileLayout = () => (
  <Columns>
    <Stack>
      <Panel title="сотрудник">
        <Specs
          items={[
            { label: "Логин", value: "ivanova" },
            { label: "Имя", value: "Ольга Иванова" },
            { label: "Отдел", value: "Конструкторский отдел" },
            { label: "Должность", value: "Инженер-библиотекарь" },
          ]}
        />
      </Panel>
      <Panel title="роли и права">
        <Specs
          layout="tight"
          items={[
            { label: "Библиотекари", value: <Chip tone="added">есть</Chip> },
            { label: "Схемотехники", value: <Chip>нет</Chip> },
          ]}
        />
      </Panel>
    </Stack>
    <Stack>
      <Panel title="мои правки в справочнике" aside={<a href="#">все 73 записи</a>}>
        <DataTable
          flow
          compact
          columns={[
            { key: "event", label: "Событие" },
            { key: "when", label: "Когда", kind: "desc" },
            { key: "target", label: "Компонент", kind: "pn" },
          ]}
          rows={[
            { event: <Chip tone="added" event>добавлен</Chip>, when: "22.09.2026 17:04", target: "CONNECTOR #504" },
            { event: <Chip tone="edited" event>изменён</Chip>, when: "21.09.2026 11:25", target: "CAPACITOR #165" },
          ]}
        />
      </Panel>
    </Stack>
  </Columns>
);
