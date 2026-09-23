import { Panel, Specs } from "sculptor-ui";

export const WithSpecs = () => (
  <Panel title="сотрудник">
    <Specs
      items={[
        { label: "Логин", value: "ivanova" },
        { label: "Отдел", value: "Конструкторский отдел" },
        { label: "Последний вход", value: "23.09.2026 13:59" },
      ]}
    />
  </Panel>
);

export const WithAsideLink = () => (
  <Panel title="мои правки в справочнике" aside={<a href="#">все 73 записи</a>}>
    <Specs
      layout="tight"
      items={[
        { label: "22.09.2026 17:04", value: "CONNECTOR #504 — добавлен" },
        { label: "21.09.2026 11:25", value: "CAPACITOR #165 — изменён" },
      ]}
    />
  </Panel>
);

export const PaddedText = () => (
  <Panel title="как пользоваться" padded>
    <p style={{ margin: 0 }}>
      Выберите группу слева, чтобы отфильтровать и отредактировать компоненты.
      Поиск в шапке проходит по всем группам сразу: часть Vendor PN, OY PN,
      описания или производителя.
    </p>
  </Panel>
);
