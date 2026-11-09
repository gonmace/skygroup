from django.urls import path

from . import views

app_name = 'reg_construccion'

urlpatterns = [
    path('registros/construccion/', views.lista, name='lista'),
    path('registros/construccion/activar/', views.activar, name='activar'),
    path('registros/construccion/<int:pk>/', views.detalle, name='detalle'),
    path('registros/construccion/<int:pk>/pdf/', views.pdf, name='pdf'),
    path('registros/construccion/<int:pk>/datos/', views.datos, name='datos'),
    path('registros/construccion/<int:pk>/nueva-visita/', views.nueva_visita, name='nueva_visita'),
    path('registros/construccion/<int:pk>/concluir/', views.concluir, name='concluir'),
    path('registros/construccion/<int:pk>/eliminar/', views.eliminar, name='eliminar'),
]
