from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import PurchaseHeader, PurchaseLine, PurchaseMatching, Supplier

admin.site.register(PurchaseHeader)
admin.site.register(PurchaseLine)
admin.site.register(PurchaseMatching)
admin.site.register(Supplier, SimpleHistoryAdmin)
