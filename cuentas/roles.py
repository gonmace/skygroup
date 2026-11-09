"""Catálogo fijo de roles base, alineado al RACI de PMBOK.

El código solo razona sobre estos roles base (o sobre capacidades). Cada empresa define
sus propios nombres visibles (`RolEmpresa`: «ITO», «Buscador», «Supervisor»…) colgados
de uno de estos roles base. El «Administrador» de la plataforma no es un rol de empresa:
es `User.is_superuser`.
"""
from django.db import models


class RolBase(models.TextChoices):
    COORDINADOR = 'COORDINADOR', 'Coordinador'
    MIEMBRO = 'MIEMBRO', 'Ejecutor'
    ESPECIALISTA = 'ESPECIALISTA', 'Especialista'
    OBSERVADOR = 'OBSERVADOR', 'Observador'


# Nombre con el que se siembra el RolEmpresa de cada rol base al crear una empresa.
NOMBRE_INICIAL = {rol.value: rol.label for rol in RolBase}

# Letra RACI: A=Accountable, R=Responsible, C=Consulted, I=Informed.
RACI_LETRA = {
    RolBase.COORDINADOR: 'A',
    RolBase.MIEMBRO: 'R',
    RolBase.ESPECIALISTA: 'C',
    RolBase.OBSERVADOR: 'I',
}
