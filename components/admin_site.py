"""Своя админка: служебные модели справочника вынесены своими разделами.

Среди 27 таблиц компонентов «Выпадающие списки» терялись, поэтому на
главной странице админки они показываются своим разделом. Туда же, в
отдельный раздел, ушли журнал, картинки посадочных мест и заявки на рендер:
это не таблицы компонентов, их смотрят, а не правят, и в общем списке
по алфавиту они стояли между «Индуктивностями» и «Конденсаторами».
Отдельное приложение ради них заводить незачем — достаточно переложить
модели в свой раздел списка.

Раньше то же самое делалось подменой ``admin.site.get_app_list`` на лету.
Замена метода у чужого объекта переживает не каждое обновление Django,
а штатный способ — свой класс сайта, объявленный в ``AdminConfig``.
"""

from django.contrib.admin import AdminSite

# (заголовок раздела, модели) — в этом порядке разделы встают после
# остальных
SECTIONS = (
    ("Журнал и изображения",
     ("ComponentChange", "FootprintImage", "StepRenderJob")),
    ("Конструктор выпадающих списков", ("OptionField",)),
)


class ComponentsAdminSite(AdminSite):
    site_header = "Sculptor"
    site_title = "Sculptor · администрирование"
    index_title = "Компоненты и параметры"

    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)
        # Только на главной. На странице раздела (app_label задан) Django
        # собирает крошку из имён всех разделов списка подряд, и второй
        # раздел с тем же app_label выходил в ней склеенным с первым:
        # «Справочник компонентов Конструктор выпадающих списков».
        if app_label is not None:
            return app_list

        for title, names in SECTIONS:
            section = _take_section(app_list, title, names)
            if section:
                app_list.append(section)
        return [app for app in app_list if app.get("models")]


def _take_section(app_list, title, names):
    """Вынимает модели ``names`` из их разделов и собирает из них новый.

    Порядок моделей — как в ``names``, а не по алфавиту: так раздел читается
    одинаково, сколько бы моделей в нём ни было видно этому пользователю.
    """
    moved, source = {}, None
    for app in app_list:
        for model in list(app.get("models", [])):
            if model.get("object_name") in names:
                app["models"].remove(model)
                moved[model["object_name"]] = model
                source = app

    if not moved:
        return None
    return {
        "name": title,
        "app_label": source["app_label"],
        "app_url": source["app_url"],
        "has_module_perms": source.get("has_module_perms", True),
        "models": [moved[name] for name in names if name in moved],
    }
