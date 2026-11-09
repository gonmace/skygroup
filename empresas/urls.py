from django.urls import path

from . import views

app_name = 'empresas'

urlpatterns = [
    path('marca/tema.css', views.tema_css, name='tema_css'),
]
