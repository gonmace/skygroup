from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path('ws/empresa/<slug:slug>/notificaciones/', consumers.NotificacionesConsumer.as_asgi()),
]
