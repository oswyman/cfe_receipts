from django import forms


class RecibosForm(forms.Form):
    archivos = forms.FileField(
        widget=forms.ClearableFileInput(attrs={'multiple': True, 'accept': '.pdf'}),
        label='Recibos PDF (puedes seleccionar varios)',
    )
