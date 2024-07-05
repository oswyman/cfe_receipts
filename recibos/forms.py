from django import forms
from .models import Recibo

class ReciboForm(forms.ModelForm):
    class Meta:
        model = Recibo
        fields = ['archivo']
