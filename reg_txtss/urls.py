from django.urls import path

from . import views

app_name = 'reg_txtss'

urlpatterns = [
    path('registros/txtss/', views.lista, name='lista'),
    path('registros/txtss/activar/', views.activar, name='activar'),
    path('registros/txtss/<int:pk>/', views.detalle, name='detalle'),
    path('registros/txtss/<int:pk>/pdf/', views.pdf, name='pdf'),
    path('registros/txtss/<int:pk>/concluir/', views.concluir, name='concluir'),
    path('registros/txtss/<int:pk>/copiar/', views.copiar, name='copiar'),
    path('registros/txtss/<int:pk>/fecha/', views.cambiar_fecha, name='fecha'),
    path('registros/txtss/<int:pk>/responsable/', views.cambiar_responsable, name='responsable'),
    path('registros/txtss/<int:pk>/eliminar/', views.eliminar, name='eliminar'),
    path('registros/txtss/<int:pk>/restaurar/', views.restaurar, name='restaurar'),
    path('registros/txtss/<int:pk>/formatear/', views.formatear, name='formatear'),
]
