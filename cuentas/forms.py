from django import forms
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm


class LoginForm(AuthenticationForm):
    """Login por correo. El campo se sigue llamando `username` (lo exige axes)."""

    username = forms.EmailField(
        label='Correo', widget=forms.EmailInput(attrs={'autofocus': True, 'autocomplete': 'email', 'class': 'input input-bordered w-full'}),
    )
    password = forms.CharField(
        label='Contraseña', strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'current-password', 'class': 'input input-bordered w-full'}),
    )


_INPUT = {'class': 'input input-bordered w-full'}


class RegistroForm(forms.Form):
    """Paso 1 del alta por dominio: solo pide el correo (y el nombre, opcional)."""

    email = forms.EmailField(label='Correo', widget=forms.EmailInput(attrs={**_INPUT, 'autofocus': True, 'autocomplete': 'email'}))
    first_name = forms.CharField(label='Nombre', max_length=150, required=False, widget=forms.TextInput(attrs=_INPUT))
    last_name = forms.CharField(label='Apellido', max_length=150, required=False, widget=forms.TextInput(attrs=_INPUT))


class RegistroConfirmarForm(SetPasswordForm):
    """Paso 2: nombre y contraseña de la cuenta nueva (los validadores de contraseña de Django aplican)."""

    first_name = forms.CharField(label='Nombre', max_length=150, required=False, widget=forms.TextInput(attrs=_INPUT))
    last_name = forms.CharField(label='Apellido', max_length=150, required=False, widget=forms.TextInput(attrs=_INPUT))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in ('new_password1', 'new_password2'):
            self.fields[campo].widget.attrs.update(_INPUT)
