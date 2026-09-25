"""HTMX: запросы, которые обновляют кусок страницы, а не её целиком.

HTMX шлёт обычные запросы к обычным видам, только с заголовком
``HX-Request: true``, и вставляет ответ в указанное место страницы. Виды
отличают такой запрос по ``request.htmx`` и отвечают фрагментом — частичным
шаблоном Django (``"шаблон.html#фрагмент"``).

Здесь — то, без чего это ломается незаметно:

**Истёкшая сессия.** Весь сайт закрыт входом (``LoginRequiredMiddleware``).
Когда сессия истечёт, запрос за фрагментом получит перенаправление на вход.
Браузер выполняет его сам, ещё до HTMX, и тот послушно вставляет целую
страницу входа внутрь таблицы или вкладки. Поэтому для HTMX-запросов
перенаправление подменяется заголовком ``HX-Redirect``: по нему HTMX уходит
по адресу целиком, как обычный переход.

**Кэш браузера.** Один адрес отдаёт то страницу, то фрагмент. Без
``Vary: HX-Request`` кнопка «Назад» может показать голый фрагмент без
оформления.

Стоит в цепочке до ``LoginRequiredMiddleware``: middleware выше по списку
видит ответ тех, что ниже, — в том числе перенаправление на вход.
"""

from django.http import HttpResponse
from django.utils.cache import patch_vary_headers

HEADER = "HX-Request"


def is_htmx(request):
    """Пришёл ли запрос от HTMX — за фрагментом, а не за страницей."""
    return request.headers.get(HEADER) == "true"


def targets(request, element_id):
    """Вставит ли HTMX ответ в элемент с этим id (заголовок ``HX-Target``).

    Один адрес может отдавать разные куски — смотря куда их просят:
    карточка компонента открывается и страницей, и краткой панелью рядом
    со списком. Ответы тогда различаются ещё и этим заголовком — вид должен
    добавить его в ``Vary``, иначе браузер может подставить из кэша не тот
    кусок.
    """
    return is_htmx(request) and request.headers.get("HX-Target") == element_id


class HtmxMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.htmx = is_htmx(request)
        response = self.get_response(request)

        if (request.htmx and 300 <= response.status_code < 400
                and response.has_header("Location")):
            # Пустой ответ 200, а не 204: заголовок перехода HTMX читает до
            # вставки, и вставлять тут нечего — страница всё равно уйдёт
            response = _redirect_page(response["Location"])

        patch_vary_headers(response, (HEADER,))
        return response


def _redirect_page(location):
    response = HttpResponse(status=200)
    response["HX-Redirect"] = location
    return response


def refresh_page():
    """Ответ «перезагрузите страницу целиком».

    Для случаев, когда фрагмент уже нечем обновлять: например, картинка
    посадочного места дорисовалась, и показать надо новую страницу, а не
    новый кусок старой.
    """
    response = HttpResponse(status=200)
    response["HX-Refresh"] = "true"
    return response
