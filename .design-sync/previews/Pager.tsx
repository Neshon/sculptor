import { Pager, Panel } from "sculptor-ui";

export const MiddlePage = () => (
  <Panel>
    <Pager page={3} pages={58} total={1433} hrefFor={(page) => `?page=${page}`} />
  </Panel>
);

export const FirstPage = () => (
  <Panel>
    <Pager page={1} pages={2} hrefFor={(page) => `?page=${page}`} />
  </Panel>
);
