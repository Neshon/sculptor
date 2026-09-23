import { Button, FormBar, FormGrid, Panel, SelectField, TextField } from "sculptor-ui";

export const BoardForm = () => (
  <Panel title="карточка платы">
    <FormGrid columns={2}>
      <TextField label="Номер платы" required defaultValue="HSBP-5S01" hint="Номер платы без ревизии" />
      <TextField label="Наименование" defaultValue="Бэкплейн HSBP-5S.01" />
      <SelectField label="Тип платы" defaultValue="backplane"
                   options={[{ value: "backplane", label: "Бэкплейн" }, { value: "riser", label: "Райзер" }]} />
      <TextField label="Компания-разработчик" defaultValue="OpenYard" />
      <TextField label="Назначение" multiline wide
                 defaultValue="Подключение пяти накопителей SFF к материнской плате" />
    </FormGrid>
    <FormBar>
      <Button variant="primary" type="submit">Завести плату</Button>
      <Button href="#" variant="ghost">Отмена</Button>
    </FormBar>
  </Panel>
);

export const ThreeColumns = () => (
  <Panel title="электрические параметры">
    <FormGrid>
      <TextField label="Value" defaultValue="110 kOhm" />
      <TextField label="Tolerance" defaultValue="±1%" />
      <TextField label="Power dissipation, W" defaultValue="1/16" />
    </FormGrid>
  </Panel>
);
