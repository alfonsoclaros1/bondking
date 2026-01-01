from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("bondking_app.urls")),  # send everything else to your app
    
]
