from django.urls import path

from . import views

app_name = 'notificaciones'

urlpatterns = [
    path('notificaciones/', views.lista, name='lista'),
    path('notificaciones/<int:pk>/leer/', views.leer, name='leer'),
    path('notificaciones/leer-todas/', views.leer_todas, name='leer_todas'),
]
