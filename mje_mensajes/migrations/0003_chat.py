"""De la bandeja de avisos (con «Listo») al chat: conversaciones, lectura por persona y adjuntos.

Los mensajes con remitente pasan a ser mensajes de la conversación DIRECTA entre remitente y destinatario
(lo aún sin confirmar queda como no leído para el destinatario). Los avisos de skyBot se eliminan: al
enviarse ya generaron su notificación en la campana, que es donde viven ahora."""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import mje_mensajes.models


def migrar(apps, schema_editor):
    Mensaje = apps.get_model('mje_mensajes', 'Mensaje')
    Conversacion = apps.get_model('mje_mensajes', 'Conversacion')
    Participacion = apps.get_model('mje_mensajes', 'Participacion')

    Mensaje.objects.filter(autor__isnull=True).delete()
    convs, ultimo, primer_sin_leer = {}, {}, {}
    for m in Mensaje.objects.select_related('destinatario').order_by('id'):
        a, b = m.autor_id, m.destinatario.user_id
        if a == b:
            m.delete()
            continue
        lo, hi = sorted((a, b))
        clave = (m.empresa_id, lo, hi)
        if clave not in convs:
            convs[clave] = Conversacion.objects.create(
                empresa_id=m.empresa_id, tipo='directo', directo_a_id=lo, directo_b_id=hi)
        conv = convs[clave]
        m.conversacion = conv
        m.save(update_fields=['conversacion'])
        ultimo[conv.pk] = (m.id, m.creado)
        if m.confirmado is None and not m.descartado:
            primer_sin_leer.setdefault((conv.pk, b), m.id)
    for (empresa_id, lo, hi), conv in convs.items():
        maximo, creado = ultimo[conv.pk]
        Conversacion.objects.filter(pk=conv.pk).update(ultimo_mensaje_en=creado)
        for uid in (lo, hi):
            sin_leer = primer_sin_leer.get((conv.pk, uid))
            Participacion.objects.create(
                conversacion=conv, user_id=uid, ultimo_leido=(sin_leer - 1) if sin_leer else maximo)
    for modelo in ('RolPermiso', 'UsuarioPermiso'):   # la capacidad «enviar» ya no existe: todos pueden escribir
        apps.get_model('cuentas', modelo).objects.filter(capacidad='mensajes.enviar').delete()


class Migration(migrations.Migration):
    dependencies = [
        ('mje_mensajes', '0002_traer_de_jor_mensajes'),
        ('cuentas', '0007_dominios_correos_bloqueados'),
        ('empresas', '0002_contratista'),
        ('proyectos', '0004_estados_unificados'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Conversacion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tipo', models.CharField(choices=[('general', 'General'), ('proyecto', 'Proyecto'), ('directo', 'Directo')], max_length=10)),
                ('creada', models.DateTimeField(auto_now_add=True)),
                ('ultimo_mensaje_en', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('directo_a', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('directo_b', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='conversaciones', to='empresas.empresa')),
                ('proyecto', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='conversaciones', to='proyectos.proyecto')),
            ],
            options={'verbose_name': 'Conversación', 'verbose_name_plural': 'Conversaciones'},
        ),
        migrations.AddConstraint(
            model_name='conversacion',
            constraint=models.UniqueConstraint(condition=models.Q(('tipo', 'general')), fields=('empresa',), name='msj_un_general'),
        ),
        migrations.AddConstraint(
            model_name='conversacion',
            constraint=models.UniqueConstraint(condition=models.Q(('tipo', 'proyecto')), fields=('proyecto',), name='msj_un_proyecto'),
        ),
        migrations.AddConstraint(
            model_name='conversacion',
            constraint=models.UniqueConstraint(condition=models.Q(('tipo', 'directo')), fields=('empresa', 'directo_a', 'directo_b'), name='msj_un_directo'),
        ),
        migrations.CreateModel(
            name='Participacion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ultimo_leido', models.PositiveBigIntegerField(default=0, help_text='Id del último mensaje leído.')),
                ('conversacion', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='participaciones', to='mje_mensajes.conversacion')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={'verbose_name': 'Participación', 'verbose_name_plural': 'Participaciones'},
        ),
        migrations.AddConstraint(
            model_name='participacion',
            constraint=models.UniqueConstraint(fields=('conversacion', 'user'), name='msj_participacion_unica'),
        ),
        # ── Mensaje: de «aviso a una persona» a «mensaje de una conversación» ──
        migrations.RemoveIndex(model_name='mensaje', name='mensajes_me_destina_8577d1_idx'),
        migrations.AddField(
            model_name='mensaje', name='conversacion',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='mensajes', to='mje_mensajes.conversacion'),
        ),
        migrations.AddField(model_name='mensaje', name='editado', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(
            model_name='mensaje', name='menciones',
            field=models.ManyToManyField(blank=True, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.RenameField('mensaje', 'cuerpo', 'texto'),
        migrations.RenameField('mensaje', 'enviado', 'creado'),
        migrations.RenameField('mensaje', 'remitente', 'autor'),
        migrations.AlterField(model_name='mensaje', name='texto', field=models.TextField(blank=True, verbose_name='Mensaje')),
        migrations.RunPython(migrar, migrations.RunPython.noop),
        migrations.RemoveField(model_name='mensaje', name='destinatario'),
        migrations.RemoveField(model_name='mensaje', name='confirmado'),
        migrations.RemoveField(model_name='mensaje', name='descartado'),
        migrations.RemoveField(model_name='mensaje', name='dia_cerrado'),
        migrations.RemoveField(model_name='mensaje', name='empresa'),
        migrations.AlterField(
            model_name='mensaje', name='conversacion',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mensajes', to='mje_mensajes.conversacion'),
        ),
        migrations.AlterModelOptions(name='mensaje', options={'ordering': ['id'], 'verbose_name': 'Mensaje', 'verbose_name_plural': 'Mensajes'}),
        migrations.AddIndex(model_name='mensaje', index=models.Index(fields=['conversacion', 'id'], name='msj_conv_id_idx')),
        migrations.CreateModel(
            name='AdjuntoMensaje',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('archivo', models.FileField(max_length=300, storage=mje_mensajes.models.almacenamiento_privado, upload_to=mje_mensajes.models.ruta_adjunto)),
                ('nombre', models.CharField(max_length=200)),
                ('mime_type', models.CharField(blank=True, max_length=100)),
                ('tamano', models.PositiveBigIntegerField(default=0)),
                ('sha256', models.CharField(blank=True, db_index=True, max_length=64)),
                ('mensaje', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='adjuntos', to='mje_mensajes.mensaje')),
            ],
            options={'verbose_name': 'Adjunto de mensaje', 'verbose_name_plural': 'Adjuntos de mensajes', 'ordering': ['id']},
        ),
    ]
