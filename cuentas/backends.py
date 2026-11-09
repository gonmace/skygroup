"""Backend de autenticación por correo (case-insensitive)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    """Autentica con el correo como identificador.

    El form de login pasa el correo en `username` (compatible con django-axes, que registra
    ese valor para el lockout).
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        email = username or kwargs.get('email')
        if email is None or password is None:
            return None
        email = email.strip()
        user = User.objects.filter(email__iexact=email).order_by('id').first()
        if user is None:
            User().set_password(password)  # tiempo de respuesta constante
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
