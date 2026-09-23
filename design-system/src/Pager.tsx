const DISABLED = { opacity: 0.4 };

export interface PagerProps {
  /** Текущая страница, с 1. */
  page: number;
  /** Всего страниц. */
  pages: number;
  /** Всего записей — показывается справа («всего 1433»). */
  total?: number;
  /** Адрес страницы; без него кнопки рисуются кнопками, а не ссылками. */
  hrefFor?: (page: number) => string;
}

/**
 * Постраничная навигация под таблицей: «первая», «назад», «стр. N из M»,
 * «вперёд», «последняя». Внутри `Panel`, после `DataTable`.
 */
export function Pager({ page, pages, total, hrefFor }: PagerProps) {
  const link = (target: number, text: string) =>
    hrefFor
      ? <a className="btn" href={hrefFor(target)}>{text}</a>
      : <button className="btn" type="button">{text}</button>;
  const off = (text: string) =>
    <span className="btn" aria-disabled="true" style={DISABLED}>{text}</span>;

  return (
    <div className="pager">
      {page > 1 ? <>{link(1, "« первая")}{link(page - 1, "назад")}</> : off("« первая")}
      <span className="pager__pos">стр. {page} из {pages}</span>
      {page < pages ? <>{link(page + 1, "вперёд")}{link(pages, "последняя »")}</>
                    : off("последняя »")}
      {total != null && (
        <>
          <span className="pager__spacer" />
          <span className="muted">всего {total}</span>
        </>
      )}
    </div>
  );
}
