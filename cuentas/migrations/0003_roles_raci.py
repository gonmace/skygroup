from django.db import migrations, models

NUEVA_BASE = {'PMO': 'COORDINADOR', 'DIRECTOR': 'COORDINADOR', 'PATROCINADOR': 'OBSERVADOR', 'INTERESADO': 'OBSERVADOR'}
# Nombres con los que se sembraron los roles antiguos; solo esos se fusionan (los demás conservan su nombre).
SEMBRADOS = {'PMO': 'PMO', 'DIRECTOR': 'Director de Proyecto', 'PATROCINADOR': 'Patrocinador', 'INTERESADO': 'Interesado'}
NOMBRE_NUEVO = {'COORDINADOR': 'Coordinador', 'OBSERVADOR': 'Observador'}
SOBREVIVE = {'COORDINADOR': 'PMO', 'OBSERVADOR': 'PATROCINADOR'}  # base antigua cuyo rol sembrado se conserva


def a_raci(apps, schema_editor):
    RolEmpresa = apps.get_model('cuentas', 'RolEmpresa')
    Membresia = apps.get_model('cuentas', 'Membresia')
    AccesoModulo = apps.get_model('cuentas', 'AccesoModulo')
    for rol in RolEmpresa.objects.filter(rol_base__in=NUEVA_BASE).order_by('empresa_id', 'orden', 'pk'):
        nueva = NUEVA_BASE[rol.rol_base]
        antigua = rol.rol_base
        sembrado = rol.nombre == SEMBRADOS[antigua]
        if sembrado and antigua != SOBREVIVE[nueva]:
            destino = RolEmpresa.objects.filter(  # el sobreviviente puede estar ya migrado (orden de proceso)
                empresa_id=rol.empresa_id, rol_base__in=[SOBREVIVE[nueva], nueva],
                nombre__in=[SEMBRADOS[SOBREVIVE[nueva]], NOMBRE_NUEVO[nueva]]).exclude(pk=rol.pk).first()
            if destino is not None:  # fusionar en el rol sembrado que se conserva
                Membresia.objects.filter(rol=rol).update(rol=destino)
                AccesoModulo.objects.filter(rol_override=rol).update(rol_override=destino)
                rol.delete()
                continue
        rol.rol_base = nueva
        if sembrado and not RolEmpresa.objects.filter(
                empresa_id=rol.empresa_id, nombre__iexact=NOMBRE_NUEVO[nueva]).exclude(pk=rol.pk).exists():
            rol.nombre = NOMBRE_NUEVO[nueva]
        rol.save()


class Migration(migrations.Migration):

    dependencies = [
        ('cuentas', '0002_membresia_contratista'),
    ]

    operations = [
        migrations.AlterField(
            model_name='rolempresa',
            name='rol_base',
            field=models.CharField(
                choices=[('COORDINADOR', 'Coordinador'), ('MIEMBRO', 'Miembro del equipo'),
                         ('ESPECIALISTA', 'Especialista'), ('OBSERVADOR', 'Observador')],
                max_length=20, verbose_name='Rol base (RACI)'),
        ),
        migrations.RunPython(a_raci, migrations.RunPython.noop),
    ]
