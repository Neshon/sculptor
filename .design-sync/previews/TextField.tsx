import { FormGrid, Panel, TextField } from "sculptor-ui";

export const States = () => (
  <Panel title="основные сведения">
    <FormGrid columns={2}>
      <TextField label="Vendor PN" required defaultValue="RC0402FR-07110KL" />
      <TextField label="OY ID" locked defaultValue="ID_R_001436" hint="Следующий свободный номер, назначается автоматически" />
      <TextField label="GBT PN" defaultValue="Rс0402" error="Допустимы латинские буквы, цифры и знаки препинания." />
      <TextField label="Vendor" defaultValue="Yageo" />
    </FormGrid>
  </Panel>
);

export const Multiline = () => (
  <Panel title="описание">
    <FormGrid columns={1}>
      <TextField
        label="Description"
        required
        multiline
        rows={3}
        defaultValue="Chip Resistor, 0402, 110 kOhm, ±1%, 1/16W"
      />
    </FormGrid>
  </Panel>
);
