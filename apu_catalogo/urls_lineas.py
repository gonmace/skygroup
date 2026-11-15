from django.urls import path

from . import views_lineas

app_name = 'apu_lineas'

urlpatterns = [
    path('apu/lista/<int:pk>/eliminar/', views_lineas.apu_eliminar, name='apu_eliminar'),
    path('apu/lista/<int:item_pk>/lineas/<int:pk>/', views_lineas.linea_editar, name='linea_editar'),
    path('apu/lista/<int:item_pk>/lineas/<int:pk>/quitar/', views_lineas.linea_quitar, name='linea_quitar'),
]
