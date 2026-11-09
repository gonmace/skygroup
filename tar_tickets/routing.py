from django.urls import path

from .consumers import TableroConsumer

websocket_urlpatterns = [
    path('ws/empresa/<slug:slug>/tareas/', TableroConsumer.as_asgi()),
]
