from django.urls import path

from . import views

app_name = 'proyectos'

# Se montan bajo /<slug>/ (EmpresaMiddleware). La URL usa «proyectos» aunque la empresa
# los llame «sitios»: la ruta es estable y el nombre visible es configurable.
urlpatterns = [
    path('proyectos/', views.lista, name='lista'),
    path('proyectos/nuevo/', views.editar, name='nuevo'),
    path('proyectos/importar/', views.importar, name='importar'),
    path('proyectos/plantilla.xlsx', views.plantilla, name='plantilla'),
    path('proyectos/tipos/', views.tipos, name='tipos'),
    path('proyectos/tipos/<int:pk>/eliminar/', views.tipo_eliminar, name='tipo_eliminar'),
    path('proyectos/<int:pk>/', views.detalle, name='detalle'),
    path('proyectos/<int:pk>/editar/', views.editar, name='editar'),
    path('proyectos/<int:pk>/eliminar/', views.eliminar, name='eliminar'),
]
