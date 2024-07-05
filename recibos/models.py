from django.db import models

class Recibo(models.Model):
    archivo = models.FileField(upload_to='recibos/')
    fecha_subida = models.DateTimeField(auto_now_add=True)
