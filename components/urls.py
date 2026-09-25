from django.urls import path

from . import change_views, image_views, link_views, search_views, views

app_name = "components"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("search/", search_views.global_search, name="search"),
    # до маршрута со слагом, иначе «changelog» приняли бы за группу
    path("changelog/", views.changelog, name="changelog"),
    path("duplicates/", views.duplicates, name="duplicates"),
    path("links/import/", link_views.link_import, name="link-import"),
    path("links/add/", link_views.link_add, name="link-add"),
    # история — до маршрута со слагом, иначе «changes» приняли бы за группу
    path("changes/", change_views.change_log, name="changes"),
    # состояние заявки на рендер — его спрашивает блок в карточке (HTMX).
    # До маршрутов со слагом по той же причине, что и журнал
    path("render-jobs/<int:pk>/", image_views.render_job_status,
         name="render-job"),
    path("changes/<int:pk>/", change_views.component_change, name="change"),
    path("<slug:slug>/", views.component_list, name="list"),
    path("<slug:slug>/new/", views.ComponentEditView.as_view(), name="create"),
    # ключ строковый: у таблицы Parts роль PK играет текстовый «OY ID»
    path("<slug:slug>/<str:pk>/", views.component_detail, name="detail"),
    path("<slug:slug>/<int:pk>/edit/", views.ComponentEditView.as_view(), name="edit"),
    path("<slug:slug>/<int:pk>/delete/", views.component_delete, name="delete"),
    path("<slug:slug>/<int:pk>/image/", image_views.footprint_image,
         name="image"),
]
