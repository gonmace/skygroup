from django.urls import path

from . import api_interna, views

app_name = 'jor_actividades'

urlpatterns = [
    path('api/jor/interno/actividades/pendientes/', api_interna.pendientes, name='api_pendientes'),
    path('api/jor/interno/actividades/clasificar/', api_interna.clasificar, name='api_clasificar'),
    path('jornadas/etiquetas/', views.etiquetas, name='etiquetas'),
    path('jornadas/etiquetas/a-proyectos/', views.etiquetas_a_proyectos, name='etiquetas_a_proyectos'),
    path('jornadas/etiquetas/<int:pk>/', views.etiqueta_accion, name='etiqueta_accion'),
    path('jornadas/categorias/', views.categorias, name='categorias'),
    path('jornadas/categorias/<int:pk>/', views.categoria_editar, name='categoria_editar'),
]
