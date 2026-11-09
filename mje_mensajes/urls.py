from django.urls import path

from . import api_interna, views

app_name = 'mje_mensajes'

urlpatterns = [
    path('api/mensajes/interno/cerrar-dia/', api_interna.cerrar_dia, name='api_cerrar_dia'),
    path('api/jor/interno/mensajes/cerrar-dia/', api_interna.cerrar_dia),   # ruta anterior: los cron/n8n ya configurados
    path('mensajes/', views.bandeja, name='bandeja'),
    path('mensajes/panel/', views.panel, name='panel'),
    path('mensajes/resumen/', views.resumen, name='resumen'),
    path('mensajes/personas/', views.personas, name='personas'),
    path('mensajes/c/<int:pk>/', views.conversacion, name='conversacion'),
    path('mensajes/c/<int:pk>/antiguos/', views.mas_antiguos, name='antiguos'),
    path('mensajes/c/<int:pk>/nuevos/', views.nuevos, name='nuevos'),
    path('mensajes/c/<int:pk>/enviar/', views.enviar, name='enviar'),
    path('mensajes/c/<int:pk>/leido/', views.leido, name='leido'),
    path('mensajes/directo/<int:user_id>/', views.directo, name='directo'),
    path('mensajes/proyecto/<int:proyecto_id>/', views.de_proyecto, name='de_proyecto'),
    path('mensajes/m/<int:pk>/', views.mensaje, name='mensaje'),
    path('mensajes/m/<int:pk>/editar/', views.editar, name='editar'),
    path('mensajes/m/<int:pk>/borrar/', views.borrar, name='borrar'),
    path('mensajes/adjunto/<int:pk>/', views.adjunto_servir, name='adjunto'),
    path('mensajes/adjunto/<int:pk>/miniatura/', views.adjunto_miniatura, name='adjunto_miniatura'),
]
