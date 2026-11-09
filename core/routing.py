"""Rutas WebSocket de todas las apps. Cada app con consumers expone `routing.websocket_urlpatterns`."""
from mje_mensajes.routing import websocket_urlpatterns as mensajes
from notificaciones.routing import websocket_urlpatterns as notificaciones
from tar_tickets.routing import websocket_urlpatterns as tareas

# Rutas de navegador (sesión + validación de origen).
websocket_urlpatterns = [
    *mensajes,
    *notificaciones,
    *tareas,
    # Los módulos (tar_, jor_) agregan aquí sus rutas: /ws/empresa/<slug>/<modulo>/…
]
