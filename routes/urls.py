from django.urls import path, re_path

from . import views

urlpatterns = [
    path("api/route/", views.route),
    path("api/route/map/", views.map_page),
    re_path(r"^(?P<path>.*)$", views.not_found),
]
