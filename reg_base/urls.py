from django.urls import path

from . import views

app_name = 'reg_base'

urlpatterns = [
    path('registros/', views.inicio, name='inicio'),
    path('registros/config/', views.config, name='config'),
    path('registros/config/tipos-de-registro/', views.tipos_registro, name='tipos'),
    path('registros/config/tipos-de-registro/<slug:clave>/alternar/', views.tipo_alternar, name='tipo_alternar'),
    path('registros/config/tipos-de-registro/<slug:clave>/restaurar/', views.tipo_restaurar, name='tipo_restaurar'),
    path('registros/<slug:clave>/<int:pk>/revisiones/nueva/', views.revision_nueva, name='revision_nueva'),
    path('registros/<slug:clave>/<int:pk>/revisiones/vigente/', views.revision_vigente, name='revision_vigente'),
    path('registros/config/tipos/<int:pk>/eliminar/', views.tipo_eliminar, name='tipo_eliminar'),
]
