from django.contrib import admin

from .models import CategoriaAPU, Insumo, ItemModelo, LineaComposicion, PerfilCalculo, PrecioInsumo


class PrecioInline(admin.TabularInline):
    model = PrecioInsumo
    extra = 0


@admin.register(Insumo)
class InsumoAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'descripcion', 'unidad', 'tipo', 'empresa', 'activo')
    list_filter = ('empresa', 'tipo', 'activo')
    search_fields = ('codigo', 'descripcion')
    inlines = [PrecioInline]


class LineaInline(admin.TabularInline):
    model = LineaComposicion
    fk_name = 'item'
    extra = 0


@admin.register(ItemModelo)
class ItemModeloAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'descripcion', 'unidad', 'categoria', 'empresa', 'activo')
    list_select_related = ('categoria', 'empresa')
    list_filter = ('empresa', 'categoria', 'activo')
    search_fields = ('codigo', 'descripcion')
    inlines = [LineaInline]


@admin.register(PerfilCalculo)
class PerfilCalculoAdmin(admin.ModelAdmin):
    """Hasta que exista el editor en la interfaz, los perfiles se editan acá (el JSON se valida con el motor)."""
    list_display = ('nombre', 'pais', 'moneda', 'empresa', 'activo')
    list_filter = ('empresa', 'pais', 'activo')
    search_fields = ('nombre',)


@admin.register(CategoriaAPU)
class CategoriaAPUAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'empresa', 'orden', 'activo')
    list_filter = ('empresa', 'activo')
    search_fields = ('nombre',)
