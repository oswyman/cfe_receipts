from django.shortcuts import render, redirect
from django.http import HttpResponse
from .forms import RecibosForm
from .models import Recibo
import pdfplumber
import anthropic
import json
import pandas as pd
from io import BytesIO
import os
from dotenv import load_dotenv

load_dotenv()

PROMPT_TEMPLATE = """
Extrae la siguiente información del recibo de CFE y devuelve los datos en formato JSON válido, sin texto adicional antes o después del JSON:

{{
    "DATOS_DEL_CLIENTE": {{
        "NOMBRE_DEL_SERVICIO": "",
        "NUMERO_DEL_SERVICIO": "",
        "CIUDAD": "",
        "ESTADO": "",
        "TARIFA": "",
        "NO_MEDIDOR": "",
        "MULTIPLICADOR": "",
        "PERIODO_FACTURADO": ""
    }},
    "DATOS_DE_LECTURA": {{
        "LECTURA_ACTUAL": "",
        "LECTURA_ANTERIOR": "",
        "TOTAL_PERIODO": "",
        "PRECIO": "",
        "SUBTOTAL": ""
    }},
    "COSTOS_DE_LA_ENERGIA_EN_EL_MERCADO_ELECTRICO_MAYORISTA": {{
        "SUMINISTRO": "",
        "DISTRIBUCION": "",
        "TRANSMISION": "",
        "CENACE": "",
        "ENERGIA": "",
        "CAPACIDAD": "",
        "SCNMEM": "",
        "TOTAL": ""
    }},
    "DESGLOSE_DEL_IMPORTE_A_PAGAR": {{
        "CARGO_FIJO": "",
        "ENERGIA": "",
        "SUBTOTAL": "",
        "IVA": "",
        "FAC_DEL_PERIODO": "",
        "DAP": "",
        "TOTAL": ""
    }},
    "TABLA_CONSUMO_HISTORICO": [
        {{
            "PERIODO": "",
            "KWH": "",
            "IMPORTE": "",
            "PAGOS": ""
        }}
    ]
}}

Texto del recibo:

{text}
"""


def extraer_texto_pdf(pdf_file):
    """Extrae texto de las primeras dos páginas del PDF usando BytesIO (sin guardar en disco)."""
    pdf_bytes = pdf_file.read()
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        pages = pdf.pages
        text = pages[0].extract_text() or ''
        if len(pages) > 1:
            text += '\n' + (pages[1].extract_text() or '')
    return text


def extraer_datos(pdf_file):
    """Extrae datos estructurados del PDF usando la API de Claude."""
    text = extraer_texto_pdf(pdf_file)

    if not text.strip():
        return {"error": "No se pudo extraer texto del PDF. Verifica que no sea una imagen escaneada."}

    cliente = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

    try:
        message = cliente.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": PROMPT_TEMPLATE.format(text=text)
                }
            ]
        )
        respuesta = message.content[0].text.strip()

        # Limpiar bloques de código si los hay
        if respuesta.startswith("```json"):
            respuesta = respuesta[7:]
        if respuesta.startswith("```"):
            respuesta = respuesta[3:]
        if respuesta.endswith("```"):
            respuesta = respuesta[:-3]

        return json.loads(respuesta.strip())

    except json.JSONDecodeError:
        return {"error": "La IA no devolvió un JSON válido. Intenta de nuevo."}
    except anthropic.APIConnectionError:
        return {"error": "No se pudo conectar a la API de Claude. Verifica tu conexión a internet."}
    except anthropic.AuthenticationError:
        return {"error": "ANTHROPIC_API_KEY inválida o no configurada."}
    except anthropic.RateLimitError:
        return {"error": "Se alcanzó el límite de la API. Intenta en unos momentos."}
    except Exception as e:
        return {"error": f"Error inesperado: {str(e)}"}


def subir_recibo(request):
    if request.method == 'POST':
        form = RecibosForm(request.POST, request.FILES)
        if form.is_valid():
            archivos = request.FILES.getlist('archivos')
            resultados = []
            errores = []

            for archivo in archivos:
                nombre = os.path.splitext(archivo.name)[0]
                datos = extraer_datos(archivo)

                if 'error' in datos:
                    errores.append({'nombre': archivo.name, 'error': datos['error']})
                else:
                    resultados.append({'nombre': nombre, 'datos': datos})
                    archivo.seek(0)
                    Recibo.objects.create(archivo=archivo)

            request.session['resultados'] = resultados
            return render(request, 'recibos/resultados.html', {
                'resultados': resultados,
                'errores': errores,
            })
    else:
        form = RecibosForm()
    return render(request, 'recibos/subir_recibo.html', {'form': form})


def descargar_excel(request):
    resultados = request.session.get('resultados')
    if not resultados:
        return redirect('subir_recibo')

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for item in resultados:
            nombre = item['nombre'][:25]  # Excel limita nombres de hoja a 31 chars
            datos = item['datos']

            secciones = [
                ('DATOS_DEL_CLIENTE', 'Cliente'),
                ('DATOS_DE_LECTURA', 'Lectura'),
                ('COSTOS_DE_LA_ENERGIA_EN_EL_MERCADO_ELECTRICO_MAYORISTA', 'Costos MEM'),
                ('DESGLOSE_DEL_IMPORTE_A_PAGAR', 'Desglose'),
            ]

            filas = []
            for clave, etiqueta in secciones:
                if clave in datos:
                    filas.append({'Campo': f'--- {etiqueta} ---', 'Valor': ''})
                    for k, v in datos[clave].items():
                        filas.append({'Campo': k, 'Valor': v})

            if filas:
                pd.DataFrame(filas).to_excel(writer, sheet_name=nombre, index=False)

            if 'TABLA_CONSUMO_HISTORICO' in datos and datos['TABLA_CONSUMO_HISTORICO']:
                df_hist = pd.DataFrame(datos['TABLA_CONSUMO_HISTORICO'])
                df_hist.to_excel(writer, sheet_name=f'{nombre[:20]}_hist', index=False)

    output.seek(0)
    nombre_archivo = resultados[0]['nombre'] if len(resultados) == 1 else 'recibos_cfe'
    response = HttpResponse(
        output,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}.xlsx"'
    return response
