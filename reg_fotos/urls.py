from django.urls import path

from . import imagenes, views

app_name = 'reg_fotos'

urlpatterns = [
    # «Imágenes»: administración de todas las fotos de la empresa (superusuario y administradores).
    path('registros/imagenes/', imagenes.lista, name='imagenes'),
    path('registros/imagenes/descargar/', imagenes.descargar, name='imagenes_descargar'),
    path('registros/imagenes/comprimir/', imagenes.comprimir, name='imagenes_comprimir'),
    path('registros/imagenes/eliminar/', imagenes.eliminar, name='imagenes_eliminar'),
    path('registros/imagenes/<int:foto_id>/archivo/', imagenes.archivo, name='imagenes_archivo'),
    path('registros/imagenes/<int:foto_id>/miniatura/', imagenes.miniatura, name='imagenes_miniatura'),
    path('registros/fotos/<int:foto_id>/imagen/', views.imagen, name='imagen'),
    path('registros/fotos/<int:foto_id>/miniatura/', views.miniatura, name='miniatura'),
    path('registros/<slug:clave>/<int:pk>/fotos/<slug:etapa>/', views.galeria, name='galeria'),
    path('registros/<slug:clave>/<int:pk>/fotos/<slug:etapa>/subir/', views.subir, name='subir'),
    path('registros/<slug:clave>/<int:pk>/fotos/<slug:etapa>/orden/', views.orden, name='orden'),
    path('registros/<slug:clave>/<int:pk>/fotos/<slug:etapa>/<int:foto_id>/descripcion/', views.descripcion, name='descripcion'),
    path('registros/<slug:clave>/<int:pk>/fotos/<slug:etapa>/<int:foto_id>/eliminar/', views.eliminar, name='eliminar'),
]
