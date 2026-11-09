from django.urls import path

from . import views

app_name = 'jor_empleados'

urlpatterns = [
    path('jornadas/config/', views.config, name='config'),
    path('jornadas/equipo/<int:membresia_id>/acceso/', views.perfil_acceso, name='perfil_acceso'),
    path('jornadas/equipo/<int:membresia_id>/reporte/', views.perfil_reporte, name='perfil_reporte'),
    path('jornadas/equipo/<int:membresia_id>/dispositivo/liberar/', views.dispositivo_liberar, name='dispositivo_liberar'),
    path('jornadas/equipo/<int:membresia_id>/perfil/', views.perfil_editar, name='perfil_editar'),
]
