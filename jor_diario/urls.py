from django.urls import path

from . import api_interna, views

app_name = 'jor_diario'

# Se montan bajo /<slug>/jornadas/ (EmpresaMiddleware pone el prefijo de empresa).
urlpatterns = [
    path('api/jor/interno/cerrar-vencidas/', api_interna.cerrar_vencidas, name='api_cerrar_vencidas'),
    path('jornadas/', views.inicio, name='inicio'),
    path('jornadas/resumen/', views.resumen, name='resumen'),
    path('jornadas/desafio/', views.desafio, name='desafio'),
    path('jornadas/dispositivo/opciones/', views.vincular_opciones, name='vincular_opciones'),
    path('jornadas/dispositivo/vincular/', views.vincular, name='vincular'),
    path('jornadas/dispositivo/enlace/', views.vincular_enlace_crear, name='vincular_enlace_crear'),
    path('jornadas/dispositivo/enlace/estado/', views.vincular_enlace_estado, name='vincular_enlace_estado'),
    path('jornadas/vincular/listo/', views.vincular_enlace_listo, name='vincular_enlace_listo'),
    path('jornadas/vincular/<str:token>/', views.vincular_enlace, name='vincular_enlace'),
    path('jornadas/vincular/<str:token>/opciones/', views.vincular_enlace_opciones, name='vincular_enlace_opciones'),
    path('jornadas/vincular/<str:token>/registrar/', views.vincular_enlace_registrar, name='vincular_enlace_registrar'),
    path('jornadas/marca-qr/crear/', views.marca_qr_crear, name='marca_qr_crear'),
    path('jornadas/marca-qr/<str:nonce>/estado/', views.marca_qr_estado, name='marca_qr_estado'),
    path('jornadas/marcar/listo/', views.marca_qr_listo, name='marca_qr_listo'),
    path('jornadas/marcar/<str:token>/', views.marca_qr_pagina, name='marca_qr_pagina'),
    path('jornadas/marcar/<str:token>/desafio/', views.marca_qr_desafio, name='marca_qr_desafio'),
    path('jornadas/marcar/<str:token>/iniciar/', views.marca_qr_iniciar, name='marca_qr_iniciar'),
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
