from django.shortcuts import render, redirect
from django.http import HttpResponse
from .forms import ReciboForm
from .models import Recibo
import pdfplumber
import openai
import json
import pandas as pd
from io import BytesIO
import os
from dotenv import load_dotenv

# Cargar las variables de entorno desde el archivo .env
load_dotenv()

# Configurar la API de OpenAI con la clave correcta
openai.api_key = os.getenv('OPENAI_API_KEY')

def extraer_datos(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        first_page = pdf.pages[0]
        second_page = pdf.pages[1] if len(pdf.pages) > 1 else None
        text = first_page.extract_text()
        text_second_page = second_page.extract_text() if second_page else ''
        full_text = text + "\n" + text_second_page

        # Utilizar OpenAI para organizar los datos con gpt-3.5-turbo
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": f"""
                Extract the following information from the CFE receipt and provide the data clearly and structured in JSON format:

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
                    "COSTOS_DE_LA_ENERGÍA_EN_EL_MERCADO_ELECTRICO_MAYORISTA": {{
                        "SUMINISTRO": "",
                        "DISTRIBUCIÓN": "",
                        "TRANSMISIÓN": "",
                        "CENACE": "",
                        "ENERGÍA": "",
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

                Use the provided text to extract the information:

                {full_text}
                """}
            ]
        )
        datos = response.choices[0].message['content'].strip()

        if datos.startswith("```json"):
            datos = datos[7:]
        if datos.endswith("```"):
            datos = datos[:-3]

        try:
            datos_json = json.loads(datos)
        except json.JSONDecodeError as e:
            datos_json = {"error": "No se pudo extraer la información correctamente. Por favor, intente de nuevo."}

        return datos_json

def subir_recibo(request):
    if request.method == 'POST':
        form = ReciboForm(request.POST, request.FILES)
        if form.is_valid():
            recibo = form.save()
            datos = extraer_datos(recibo.archivo.path)
            request.session['datos'] = datos  # Guardar datos en la sesión
            request.session['nombre_archivo'] = os.path.splitext(recibo.archivo.name)[0]  # Guardar el nombre del archivo sin extensión
            return render(request, 'recibos/resultados.html', {'datos': datos})
    else:
        form = ReciboForm()
    return render(request, 'recibos/subir_recibo.html', {'form': form})

def descargar_excel(request):
    datos = request.session.get('datos', None)
    nombre_archivo = request.session.get('nombre_archivo', 'datos_recibo')
    if not datos:
        return redirect('subir_recibo')

    # Crear un archivo Excel en memoria
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Agregar los datos a diferentes hojas en el archivo Excel
        if 'DATOS_DEL_CLIENTE' in datos:
            df_cliente = pd.DataFrame.from_dict(datos['DATOS_DEL_CLIENTE'], orient='index', columns=['Valor'])
            df_cliente.to_excel(writer, sheet_name='Datos del Cliente')

        if 'DATOS_DE_LECTURA' in datos:
            df_lectura = pd.DataFrame.from_dict(datos['DATOS_DE_LECTURA'], orient='index', columns=['Valor'])
            df_lectura.to_excel(writer, sheet_name='Datos de Lectura')

        if 'COSTOS_DE_LA_ENERGÍA_EN_EL_MERCADO_ELECTRICO_MAYORISTA' in datos:
            df_costos = pd.DataFrame.from_dict(datos['COSTOS_DE_LA_ENERGÍA_EN_EL_MERCADO_ELECTRICO_MAYORISTA'], orient='index', columns=['Valor'])
            df_costos.to_excel(writer, sheet_name='Costos Energía Mercado')

        if 'DESGLOSE_DEL_IMPORTE_A_PAGAR' in datos:
            df_desglose = pd.DataFrame.from_dict(datos['DESGLOSE_DEL_IMPORTE_A_PAGAR'], orient='index', columns=['Valor'])
            df_desglose.to_excel(writer, sheet_name='Desglose Importe a Pagar')

        if 'TABLA_CONSUMO_HISTORICO' in datos:
            df_hist = pd.DataFrame(datos['TABLA_CONSUMO_HISTORICO'])
            df_hist.to_excel(writer, sheet_name='Consumo Histórico')

    output.seek(0)

    # Preparar la respuesta HTTP con el archivo Excel
    response = HttpResponse(output, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename={nombre_archivo}.xlsx'

    return response
