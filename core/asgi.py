import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

# get_asgi_application() dispara django.setup(): tiene que correr ANTES de importar
# routing/consumers (tocan modelos), o revienta con AppRegistryNotReady.
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from core.routing import websocket_urlpatterns  # noqa: E402

# AllowedHostsOriginValidator hace de CSRF para WebSocket; AuthMiddlewareStack resuelve
# scope['user'] desde la sesión (misma cookie que HTTP).
application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter(websocket_urlpatterns))),
})
