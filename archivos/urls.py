from django.urls import path

from . import views

app_name = 'archivos'

urlpatterns = [
    path('archivos/privado/<path:ruta>', views.privado, name='privado'),
]
