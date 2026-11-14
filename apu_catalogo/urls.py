from django.urls import path

from . import views

app_name = 'apu_catalogo'

urlpatterns = [
    path('apu/', views.inicio, name='inicio'),
    path('apu/perfiles/nuevo/', views.perfil_nuevo, name='perfil_nuevo'),
    path('apu/perfiles/<int:pk>/', views.perfil_detalle, name='perfil_detalle'),
    path('apu/perfiles/<int:pk>/editar/', views.perfil_editar, name='perfil_editar'),
    path('apu/perfiles/<int:pk>/eliminar/', views.perfil_eliminar, name='perfil_eliminar'),
    path('apu/perfiles/<int:pk>/copiar/', views.perfil_copiar, name='perfil_copiar'),
]
