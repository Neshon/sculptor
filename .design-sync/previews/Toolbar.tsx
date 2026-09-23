import { Button, DataTable, Panel, SearchField, SelectField, Toolbar, ToolbarSpacer } from "sculptor-ui";

export const ListFilters = () => (
  <Panel>
    <Toolbar>
      <SearchField title="PN, описание, производитель" />
      <SelectField placeholder="Vendor" options={[{ value: "Yageo" }, { value: "Murata" }, { value: "Samsung" }]} />
      <SelectField placeholder="Package" options={[{ value: "0402" }, { value: "0603" }]} />
      <Button variant="reset">Сбросить</Button>
      <ToolbarSpacer />
      <Button href="#">Выгрузить CSV</Button>
    </Toolbar>
    <DataTable
      flow
      columns={[
        { key: "pn", label: "Vendor PN", kind: "pn" },
        { key: "vendor", label: "Vendor", kind: "desc" },
        { key: "package", label: "Package", kind: "pn" },
      ]}
      rows={[
        { pn: "RC0402FR-07110KL", vendor: "Yageo", package: "0402" },
        { pn: "GRM188R71H104KA93D", vendor: "Murata", package: "0603" },
      ]}
    />
  </Panel>
);

export const RolesSave = () => (
  <Panel>
    <Toolbar>
      <Button variant="primary" type="submit">Сохранить роли</Button>
      <span className="muted">Администратор и доступ к админке — в админке.</span>
    </Toolbar>
  </Panel>
);
