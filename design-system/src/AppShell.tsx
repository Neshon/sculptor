import type { ReactNode } from "react";
import logo from "../../components/static/components/logo-white.svg";
import { cx } from "./cx";

export interface NavItem {
  /** Подпись пункта — ПРОПИСНЫМИ, как в меню сайта: «SERVERS», «CAPACITOR». */
  label: string;
  href?: string;
  /** Полное название в подсказке: «Конденсаторы». */
  title?: string;
  active?: boolean;
}

export interface NavSection {
  /** Заголовок группы меню: «Серверы», «Группы компонентов», «Замены». */
  title?: string;
  items: NavItem[];
}

export interface AppShellProps {
  /** Меню слева по группам; между группами — разделитель. */
  nav?: NavSection[];
  /** Логин вошедшего в шапке справа. */
  user?: string;
  /** Версия рядом с логотипом: «0.3.0». */
  version?: string;
  /** Подсказка в поле глобального поиска. */
  searchPlaceholder?: string;
  /** Содержимое страницы: `PageHeader`, затем панели. */
  children?: ReactNode;
}

/**
 * Каркас экрана Sculptor: тёмная шапка с логотипом OpenYard, глобальным
 * поиском и пользователем; меню разделов слева; содержимое справа.
 * Любой полноэкранный макет начинается с него.
 */
export function AppShell({
  nav = [], user, version, searchPlaceholder = "Глобальный поиск", children,
}: AppShellProps) {
  return (
    <>
      <header className="topbar">
        <div className="topbar__side">
          <a className="topbar__logo" href="#">
            <img src={logo} alt="OpenYard" />
          </a>
          {version != null && <span className="topbar__version">v{version}</span>}
        </div>
        <form className="topbar__search" role="search" onSubmit={(e) => e.preventDefault()}>
          <input type="search" name="q" placeholder={searchPlaceholder}
                 aria-label="Глобальный поиск" autoComplete="off" />
          <span className="topbar__hint" aria-hidden="true"><kbd>Ctrl</kbd><kbd>K</kbd></span>
        </form>
        <div className="topbar__side topbar__side--end topbar__user">
          {user != null && <a href="#"><strong>{user}</strong></a>}
          <button type="button" className="topbar__logout">выйти</button>
        </div>
      </header>
      <div className="shell">
        <nav className="rail">
          <div className="rail__scroll">
            {nav.map((section, index) => (
              <div key={index}>
                {index > 0 && <div className="rail__divider" />}
                {section.title != null && <div className="rail__title">{section.title}</div>}
                {section.items.map((item) => (
                  <a key={item.label} className={cx("rail__link", item.active && "is-active")}
                     href={item.href ?? "#"} title={item.title}>
                    <span>{item.label}</span>
                  </a>
                ))}
              </div>
            ))}
          </div>
        </nav>
        <main className="main">{children}</main>
      </div>
    </>
  );
}
