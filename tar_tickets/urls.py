from django.urls import path

from . import views

app_name = 'tar_tickets'

# Se montan bajo /<slug>/tareas/ (EmpresaMiddleware pone el prefijo de empresa).
urlpatterns = [
    path('tareas/', views.tablero, name='tablero'),
    path('tareas/fragmento/', views.fragmento, name='fragmento'),
    path('tareas/nuevo/', views.crear, name='nuevo'),
    path('tareas/mover/', views.mover, name='mover'),
    path('tareas/subticket/mover/', views.mover_subticket, name='mover_subticket'),
    path('tareas/subticket/<int:pk>/concluir/', views.concluir_subticket, name='concluir_subticket'),
    path('tareas/<int:pk>/aprobar/', views.aprobar, name='aprobar'),
    path('tareas/<int:pk>/rechazar/', views.rechazar, name='rechazar'),
    path('tareas/<int:pk>/suspender/', views.suspender, name='suspender'),
    path('tareas/mis-tickets/', views.mis_tickets, name='mis_tickets'),
    path('tareas/seguimiento/', views.seguimiento, name='seguimiento'),
    path('tareas/dashboard/', views.dashboard, name='dashboard'),
    path('tareas/archivados/', views.archivados, name='archivados'),
    path('tareas/etiquetas/', views.etiquetas, name='etiquetas'),
    path('tareas/etiquetas/agregar/', views.etiqueta_rapida, name='etiqueta_rapida'),
    path('tareas/adjunto/<int:pk>/', views.adjunto_servir, name='adjunto_servir'),
    path('tareas/adjunto/<int:pk>/miniatura/', views.adjunto_miniatura, name='adjunto_miniatura'),
    path('tareas/adjunto/<int:pk>/borrar/', views.adjunto_borrar, name='adjunto_borrar'),
    path('tareas/adjunto/<int:pk>/anotar/', views.adjunto_anotar, name='adjunto_anotar'),
    path('tareas/comentario/<int:pk>/editar/', views.comentario_editar, name='comentario_editar'),
    path('tareas/comentario/<int:pk>/borrar/', views.comentario_borrar, name='comentario_borrar'),
    path('tareas/<int:pk>/', views.detalle, name='detalle'),
    path('tareas/<int:pk>/editar/', views.editar, name='editar'),
    path('tareas/<int:pk>/comentar/', views.comentar, name='comentar'),
    path('tareas/<int:pk>/comentarios/', views.historial_chat, name='historial_chat'),
    path('tareas/<int:pk>/comentarios/nuevos/', views.comentarios_desde, name='comentarios_desde'),
    path('tareas/<int:pk>/adjuntos/', views.mas_adjuntos, name='mas_adjuntos'),
    path('tareas/<int:pk>/derivar/', views.derivar, name='derivar'),
    path('tareas/<int:pk>/dividir/', views.dividir, name='dividir'),
    path('tareas/<int:pk>/archivar/', views.archivar, name='archivar'),
    path('tareas/<int:pk>/desarchivar/', views.desarchivar, name='desarchivar'),
    path('tareas/<int:pk>/eliminar/', views.eliminar, name='eliminar'),
]
