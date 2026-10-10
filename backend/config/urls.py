from django.urls import path

from luxrocket.core.views import healthz

urlpatterns = [
    path("healthz", healthz, name="healthz"),
]
