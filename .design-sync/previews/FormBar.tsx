import { Button, FormBar, FormGrid, Panel, TextField } from "sculptor-ui";

export const SaveCancel = () => (
  <Panel>
    <FormGrid columns={1}>
      <TextField label="Comment" defaultValue="Новый компонент из BOM-файла от Gigabyte" />
    </FormGrid>
    <FormBar>
      <Button variant="primary" type="submit">Сохранить</Button>
      <Button href="#" variant="ghost">Отмена</Button>
      <Button href="#" variant="danger">Удалить позицию</Button>
    </FormBar>
  </Panel>
);
