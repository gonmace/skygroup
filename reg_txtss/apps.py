from django.apps import AppConfig


class RegTxtssConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'reg_txtss'
    verbose_name = 'TX/TSS'

    def ready(self):
        from reg_base.tipos import registrar_tipo
        registrar_tipo('txtss', self.get_model('RegTxtss'), 'reg.txtss.ver', 'reg_txtss:detalle', 'TX/TSS',
                       descripcion='Relevamiento técnico de sitio (Technical Site Survey) de postes y torres.')
