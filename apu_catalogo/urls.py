from django.urls import path

from . import views

app_name = 'apu_catalogo'

urlpatterns = [
    path('apu/', views.inicio, name='inicio'),
    path('apu/lista/', views.items, name='items'),
    path('apu/lista/<int:pk>/', views.item_detalle, name='item_detalle'),
    path('apu/proyectos/', views.proyectos, name='proyectos'),
    path('apu/proyectos/<int:pk>/incidencias/', views.incidencias, name='incidencias'),
    path('apu/insumos/', views.insumos, name='insumos'),
    path('apu/perfiles/nuevo/', views.perfil_nuevo, name='perfil_nuevo'),
    path('apu/perfiles/<int:pk>/', views.perfil_detalle, name='perfil_detalle'),
    path('apu/perfiles/<int:pk>/editar/', views.perfil_editar, name='perfil_editar'),
    path('apu/perfiles/<int:pk>/eliminar/', views.perfil_eliminar, name='perfil_eliminar'),
    path('apu/perfiles/<int:pk>/copiar/', views.perfil_copiar, name='perfil_copiar'),
]
