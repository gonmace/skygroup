from django.urls import path

from . import views

app_name = 'reg_construccion_base'

urlpatterns = [
    path('registros/construccion-base/', views.lista, name='lista'),
    path('registros/construccion-base/nueva/', views.nueva, name='nueva'),
    path('registros/hallazgos/', views.hallazgos, name='hallazgos'),
    path('registros/hallazgos/<int:pk>/', views.hallazgo_detalle, name='hallazgo_detalle'),
    path('registros/hallazgos/<int:pk>/editar/', views.hallazgo_editar, name='hallazgo_editar'),
    path('registros/hallazgos/<int:pk>/eliminar/', views.hallazgo_eliminar, name='hallazgo_eliminar'),
    path('registros/construccion-base/<int:pk>/', views.detalle, name='detalle'),
    path('registros/construccion-base/<int:pk>/datos/', views.datos, name='datos'),
    path('registros/construccion-base/<int:pk>/emitir/', views.emitir, name='emitir'),
    path('registros/construccion-base/<int:pk>/eliminar/', views.eliminar, name='eliminar'),
    path('registros/construccion-base/<int:pk>/nueva-visita/', views.nueva_visita, name='nueva_visita'),
    path('registros/construccion-base/<int:pk>/hallazgos/nuevo/', views.hallazgo_nuevo, name='hallazgo_nuevo'),
    path('registros/construccion-base/<int:pk>/pdf/', views.pdf, name='pdf'),
]
