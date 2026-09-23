import { Chip, Panel, Specs } from "sculptor-ui";

export const ComponentMain = () => (
  <Panel title="основные характеристики">
    <Specs
      items={[
        { label: "Vendor PN", value: "RC0402FR-07110KL" },
        { label: "Vendor", value: "Yageo" },
        { label: "OY PN", value: "R0402-110K-1-SBC-MU" },
        { label: "Package", value: "0402" },
        { label: "SMT_THT", value: "SMT" },
        { label: "Allegro PCB Footprint", value: "RESC1005X040" },
      ]}
    />
  </Panel>
);

export const Tight = () => (
  <Panel title="что вам доступно">
    <Specs
      layout="tight"
      items={[
        { label: "Смотреть компоненты, платы и серверы", value: <Chip tone="added">да</Chip> },
        { label: "Заводить и править компоненты", value: <Chip tone="added">да</Chip> },
        { label: "Загружать BOM и вести платы", value: <Chip>нет</Chip> },
      ]}
    />
  </Panel>
);

export const ShortLabels = () => (
  <Panel title="карточка печатного узла">
    <Specs
      layout="pairs"
      items={[
        { label: "Имя PCB", value: "HSBP-4L01" },
        { label: "Имя BOM", value: "HSBP-4L01-02C" },
        { label: "Шелкография", value: "есть" },
        { label: "Панелей", value: "4" },
      ]}
    />
  </Panel>
);
