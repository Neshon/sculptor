import { FormGrid, Panel, SelectField, Toolbar } from "sculptor-ui";

export const FormFields = () => (
  <Panel title="основные сведения">
    <FormGrid columns={2}>
      <SelectField
        label="SMT_THT"
        defaultValue="SMT"
        options={[{ value: "SMT" }, { value: "THT" }]}
      />
      <SelectField
        label="Country"
        placeholder="—"
        options={[{ value: "China" }, { value: "Japan" }, { value: "Taiwan" }, { value: "Russia" }]}
        hint="Страна производителя"
      />
    </FormGrid>
  </Panel>
);

export const AsFilter = () => (
  <Panel>
    <Toolbar>
      <SelectField placeholder="Subgroup" options={[{ value: "Fixed value resistor" }, { value: "Fixed value resistor/RUS" }]} />
      <SelectField placeholder="Tolerance" options={[{ value: "±1%" }, { value: "±5%" }]} />
    </Toolbar>
  </Panel>
);
