from django.urls import path
from . import views

urlpatterns = [
    path('', views.subir_recibo, name='subir_recibo'),
    path('descargar_excel/', views.descargar_excel, name='descargar_excel'),
]
