from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path('ws/empresa/<slug:slug>/mensajes/', consumers.MensajeriaConsumer.as_asgi()),
]
