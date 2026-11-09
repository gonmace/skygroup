from django.urls import path

from . import views

app_name = 'reg_fotos'

urlpatterns = [
    path('registros/fotos/<int:foto_id>/imagen/', views.imagen, name='imagen'),
    path('registros/fotos/<int:foto_id>/miniatura/', views.miniatura, name='miniatura'),
    path('registros/<slug:clave>/<int:pk>/fotos/<slug:etapa>/', views.galeria, name='galeria'),
    path('registros/<slug:clave>/<int:pk>/fotos/<slug:etapa>/subir/', views.subir, name='subir'),
    path('registros/<slug:clave>/<int:pk>/fotos/<slug:etapa>/orden/', views.orden, name='orden'),
    path('registros/<slug:clave>/<int:pk>/fotos/<slug:etapa>/<int:foto_id>/descripcion/', views.descripcion, name='descripcion'),
    path('registros/<slug:clave>/<int:pk>/fotos/<slug:etapa>/<int:foto_id>/eliminar/', views.eliminar, name='eliminar'),
]
