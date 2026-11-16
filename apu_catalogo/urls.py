from django.urls import path

from . import views

app_name = 'apu_catalogo'

urlpatterns = [
    path('apu/', views.inicio, name='inicio'),
    path('apu/lista/', views.items, name='items'),
    path('apu/lista/<int:pk>/', views.item_detalle, name='item_detalle'),
    path('apu/proyectos/', views.proyectos, name='proyectos'),
    path('apu/proyectos/<int:pk>/', views.proyecto_detalle, name='proyecto_detalle'),
    path('apu/proyectos/<int:pk>/pdf/', views.proyecto_pdf, name='proyecto_pdf'),
    path('apu/proyectos/habilitar/', views.habilitar, name='habilitar'),
    path('apu/proyectos/<int:pk>/cantidades/', views.cantidades_guardar, name='cantidades'),
    path('apu/proyectos/<int:pk>/incidencias/', views.incidencias, name='incidencias'),
    path('apu/insumos/', views.insumos, name='insumos'),
    path('apu/insumos/<int:pk>/editar/', views.insumo_editar, name='insumo_editar'),
    path('apu/insumos/<int:pk>/eliminar/', views.insumo_eliminar, name='insumo_eliminar'),
    path('apu/categorias/', views.categorias, name='categorias'),
    path('apu/categorias/nueva/', views.categoria_nueva, name='categoria_nueva'),
    path('apu/categorias/<int:pk>/renombrar/', views.categoria_renombrar, name='categoria_renombrar'),
    path('apu/categorias/<int:pk>/mover/', views.categoria_mover, name='categoria_mover'),
    path('apu/categorias/<int:pk>/fusionar/', views.categoria_fusionar, name='categoria_fusionar'),
    path('apu/categorias/<int:pk>/eliminar/', views.categoria_eliminar, name='categoria_eliminar'),
    path('apu/perfiles/nuevo/', views.perfil_nuevo, name='perfil_nuevo'),
    path('apu/perfiles/<int:pk>/', views.perfil_detalle, name='perfil_detalle'),
    path('apu/perfiles/<int:pk>/editar/', views.perfil_editar, name='perfil_editar'),
    path('apu/perfiles/<int:pk>/eliminar/', views.perfil_eliminar, name='perfil_eliminar'),
    path('apu/perfiles/<int:pk>/copiar/', views.perfil_copiar, name='perfil_copiar'),
]
