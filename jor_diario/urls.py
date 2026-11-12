from django.urls import path

from . import api_interna, views

app_name = 'jor_diario'

# Se montan bajo /<slug>/jornadas/ (EmpresaMiddleware pone el prefijo de empresa).
urlpatterns = [
    path('api/jor/interno/cerrar-vencidas/', api_interna.cerrar_vencidas, name='api_cerrar_vencidas'),
    path('jornadas/', views.inicio, name='inicio'),
    path('jornadas/resumen/', views.resumen, name='resumen'),
    path('jornadas/excepciones/', views.excepciones, name='excepciones'),
    path('jornadas/excepciones/<int:pk>/decidir/', views.excepcion_decidir, name='excepcion_decidir'),
    path('jornadas/iniciar/', views.iniciar, name='iniciar'),
    path('jornadas/finalizar/', views.finalizar, name='finalizar'),
    path('jornadas/mis-reportes/', views.historial, name='historial'),
    path('jornadas/equipo/', views.equipo, name='equipo'),
    path('jornadas/equipo/mapa/', views.mapa_equipo, name='mapa_equipo'),
    path('jornadas/<int:pk>/cambiar-inicio/', views.jornada_cambiar_inicio, name='jornada_cambiar_inicio'),
    path('jornadas/equipo/<int:membresia_id>/', views.persona, name='persona'),
    path('jornadas/ausencias/', views.ausencias, name='ausencias'),
    path('jornadas/ausencias/<int:pk>/decidir/', views.ausencia_decidir, name='ausencia_decidir'),
    path('jornadas/ausencias/<int:pk>/eliminar/', views.ausencia_eliminar, name='ausencia_eliminar'),
    path('jornadas/calendario/', views.calendario, name='calendario'),
    path('jornadas/calendario/<int:pk>/eliminar/', views.nota_eliminar, name='nota_eliminar'),
]

