import requests
import csv
import io
import json
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime, date, timedelta # Añadir date y timedelta
import time
from bs4 import BeautifulSoup
import pytz
import html
# from urllib.parse import quote

# --- Configuración (sin cambios) ---
TARGET_CHANNELS = [
    {"casid": "5252"},
    {"casid": "4955"}
]
CSV_URL = "https://raw.githubusercontent.com/parotris3/Mfeed/main/difusion.csv"
BASE_PROGRAM_URL = "https://www.movistarplus.es/programacion-tv/"
OUTPUT_XML_FILE = "popups.xml" # Nuevo nombre de archivo
REQUEST_DELAY = 0.5
LOCAL_TIMEZONE = pytz.timezone('Europe/Madrid')

# --- Funciones Auxiliares ---
# Debes tener aquí las definiciones completas y actualizadas de:
# obtener_datos_canal_csv(cas_id_buscar, url) -> nombre, logo, cod_cadena_tv
# formatear_fecha_xmltv(fecha_iso) -> str_fecha_xmltv | None
# obtener_detalles_programa(detail_url) -> og_title, description, image_url | None, None, None
# obtener_programacion_movistar(url, canal_nombre_target) -> lista_programas (con original_titulo, detail_url, etc.)
# prettify_xml(elem) -> str_xml_formateado
# --- Asegúrate que están presentes y correctas ---
# (Incluyo las definiciones de la última versión para completitud)

def obtener_datos_canal_csv(cas_id_buscar, url):
    print(f"INFO: Obteniendo datos del canal con CasId {cas_id_buscar} desde {url}")
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        try:
            decoded_text = response.content.decode('utf-8-sig')
        except UnicodeDecodeError:
            print("ADVERTENCIA: No se pudo decodificar como utf-8-sig, intentando con la detección automática.")
            decoded_text = response.text
        csv_file = io.StringIO(decoded_text)
        reader = csv.reader(csv_file, delimiter=',', quotechar='"')
        header = next(reader)
        try:
            casid_index = header.index('CasId')
            nombre_index = header.index('Nombre')
            logo_index = header.index('Logo')
            cod_cadena_tv_index = header.index('CodCadenaTv')
        except ValueError as e:
            print(f"ERROR: Columna requerida no encontrada en el CSV: {e}. Cabecera encontrada: {header}")
            return None, None, None
        max_index = max(casid_index, nombre_index, logo_index, cod_cadena_tv_index)
        for row in reader:
            if len(row) > max_index:
                if row[casid_index] == cas_id_buscar:
                    nombre = row[nombre_index]; logo = row[logo_index]; cod_cadena_tv = row[cod_cadena_tv_index]
                    if nombre and logo and cod_cadena_tv:
                        print(f"INFO: Canal encontrado -> Nombre: '{nombre}', Logo: '{logo}', CodCadenaTv: '{cod_cadena_tv}'")
                        return nombre, logo, cod_cadena_tv
                    else:
                        print(f"ERROR: Fila encontrada para CasId {cas_id_buscar}, pero faltan datos. Fila: {row}")
                        return None, None, None
        print(f"ERROR: No se encontró el canal con CasId {cas_id_buscar} en el CSV.")
        return None, None, None
    except requests.exceptions.RequestException as e: print(f"ERROR: No se pudo obtener el archivo CSV: {e}"); return None, None, None
    except (csv.Error, StopIteration, IndexError) as e: print(f"ERROR: Error al procesar el archivo CSV: {e}"); return None, None, None
    except Exception as e: print(f"ERROR: Error inesperado al obtener datos del canal: {e}"); return None, None, None

def formatear_fecha_xmltv(fecha_iso):
    try:
        if len(fecha_iso) > 6 and fecha_iso[-3] == ':': fecha_iso = fecha_iso[:-3] + fecha_iso[-2:]
        dt_obj = datetime.fromisoformat(fecha_iso)
        return dt_obj.strftime("%Y%m%d%H%M%S %z")
    except ValueError as e: print(f"ERROR: No se pudo formatear la fecha '{fecha_iso}': {e}"); return None

def obtener_detalles_programa(detail_url):
    if not detail_url: return None, None, None
    print(f"\nDEBUG: Procesando detalles para: {detail_url}")
    og_title = None; description = None; image_url = None
    try:
        time.sleep(REQUEST_DELAY)
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(detail_url, headers=headers, timeout=15); response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')
        og_title_tag = soup.find('meta', property='og:title')
        if og_title_tag and og_title_tag.get('content'): og_title = og_title_tag['content'].strip(); print(f"DEBUG: og:title = '{og_title}'")
        else: print("ADVERTENCIA: og:title no encontrado.")
        desc_tag = soup.find('meta', attrs={'name': 'description'})
        if desc_tag and desc_tag.get('content'):
            full_description = html.unescape(desc_tag['content'].strip())
            #print(f"DEBUG: meta name='description' (completo) = '{full_description[:100]}...'")
            separator = " - "; separator_index = full_description.find(separator)
            if separator_index != -1: description = full_description[separator_index + len(separator):].strip(); print("DEBUG: Descripción dividida por ' - '. Usando parte posterior.")
            else: description = full_description; print("DEBUG: Separador ' - ' no encontrado en descripción. Usando completa.")
        else: print("ADVERTENCIA: meta name='description' no encontrado.")
        scripts_jsonld = soup.find_all('script', type='application/ld+json')
        for script in scripts_jsonld:
            try:
                data = json.loads(script.string); items_to_check = []
                if isinstance(data, dict): items_to_check.append(data)
                elif isinstance(data, list): items_to_check.extend(data)
                for item in items_to_check:
                    if 'image' in item:
                        image_data = item['image']
                        if isinstance(image_data, str): image_url = image_data; break
                        elif isinstance(image_data, dict) and image_data.get('@type') == 'ImageObject' and 'url' in image_data: image_url = image_data['url']; break
                        elif isinstance(image_data, list) and image_data:
                             first_image = image_data[0]
                             if isinstance(first_image, str): image_url = first_image; break
                             elif isinstance(first_image, dict) and first_image.get('@type') == 'ImageObject' and 'url' in first_image: image_url = first_image['url']; break
                if image_url: break
            except (json.JSONDecodeError, AttributeError): continue
        if image_url: print("DEBUG: URL de imagen encontrada.")
        else: print("ADVERTENCIA: URL de imagen no encontrada.")
        return og_title, description, image_url
    except requests.exceptions.RequestException as e: print(f"ERROR: No se pudo obtener la página de detalle {detail_url}: {e}"); return None, None, None
    except Exception as e: print(f"ERROR: Error inesperado al procesar la página de detalle {detail_url}: {e}"); return None, None, None

def obtener_programacion_movistar(url, canal_nombre_target):
    print(f"INFO: Obteniendo programación para '{canal_nombre_target}' desde {url}")
    programas = []; program_details_from_html = {}
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=15); response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')
        program_blocks = soup.find_all('div', class_=lambda x: x and 'container_box' in x.split())
        for block in program_blocks:
            link_tag = block.find('a', href=True); title_tag = block.find('li', class_='title'); time_tag = block.find('li', class_='time')
            if link_tag and title_tag and time_tag:
                detail_url = link_tag['href']
                if detail_url.startswith('/'): detail_url = f"https://www.movistarplus.es{detail_url}"
                title = title_tag.get_text(strip=True); time_str = time_tag.get_text(strip=True); norm_title = ' '.join(title.lower().split())
                program_details_from_html[(time_str, norm_title)] = detail_url
        scripts_jsonld = soup.find_all('script', type='application/ld+json')
        if not scripts_jsonld: print(f"ERROR: No se encontraron scripts JSON-LD en {url}"); return []
        for script in scripts_jsonld:
            try:
                data = json.loads(script.string); item_list = []
                if isinstance(data, dict) and 'itemListElement' in data: item_list = data['itemListElement']
                elif isinstance(data, list): item_list = data
                for item_data in item_list:
                    item = item_data.get("item", item_data)
                    if item.get("@type") == "BroadcastEvent":
                        nombre_programa = item.get("name"); fecha_inicio_iso = item.get("startDate"); fecha_fin_iso = item.get("endDate")
                        servicio_emision = item.get("publishedOn"); nombre_canal_json = None
                        if isinstance(servicio_emision, dict): nombre_canal_json = servicio_emision.get("name")
                        if nombre_programa and fecha_inicio_iso and fecha_fin_iso and nombre_canal_json:
                            if nombre_canal_json == canal_nombre_target:
                                fecha_inicio_xmltv = formatear_fecha_xmltv(fecha_inicio_iso); fecha_fin_xmltv = formatear_fecha_xmltv(fecha_fin_iso)
                                if fecha_inicio_xmltv and fecha_fin_xmltv:
                                    detail_url_found = None
                                    try:
                                        dt_start_utc = datetime.fromisoformat(fecha_inicio_iso.replace('Z', '+00:00'))
                                        dt_start_local = dt_start_utc.astimezone(LOCAL_TIMEZONE)
                                        time_str_local = dt_start_local.strftime("%H:%M"); norm_title_json = ' '.join(nombre_programa.lower().split())
                                        key = (time_str_local, norm_title_json)
                                        if key in program_details_from_html: detail_url_found = program_details_from_html[key]
                                    except Exception as match_err: print(f"ADVERTENCIA: Error al intentar emparejar programa '{nombre_programa}': {match_err}")
                                    programas.append({"original_titulo": nombre_programa, "inicio": fecha_inicio_xmltv, "fin": fecha_fin_xmltv, "canal_nombre": nombre_canal_json, "detail_url": detail_url_found})
            except (json.JSONDecodeError, AttributeError): continue
            except Exception as e: print(f"ADVERTENCIA: Error procesando un script JSON-LD: {e}")
        print(f"INFO: Programación JSON procesada para '{canal_nombre_target}'. Total programas encontrados: {len(programas)}")
        return programas
    except requests.exceptions.RequestException as e: print(f"ERROR: No se pudo obtener la página de programación {url}: {e}"); return []
    except Exception as e: print(f"ERROR: Error inesperado al obtener la programación de {url}: {e}"); return []

def prettify_xml(elem):
    rough_string = ET.tostring(elem, 'utf-8'); reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ", encoding="UTF-8").decode('utf-8')


# --- Script Principal ---
if __name__ == "__main__":
    print("--- Iniciando generación de EPG XML para 3 días ---")
    print(f"ADVERTENCIA: Este proceso será más largo debido a la obtención de datos para 3 días.")
    start_time = time.time()

    channels_data = {}
    all_programs_processed = {} # { "NombreCanal": [lista_programas_procesados_3_dias] }

    # --- Calcular Fechas ---
    today = datetime.now(LOCAL_TIMEZONE).date()
    dates_to_process = [today + timedelta(days=i) for i in range(3)] # Hoy, mañana, pasado mañana
    date_strings = [d.strftime('%Y-%m-%d') for d in dates_to_process]
    print(f"INFO: Se procesarán las fechas: {', '.join(date_strings)}")
    # ---------------------

    # 1. Obtener info básica de canales y lista inicial de programas para 3 días
    for target in TARGET_CHANNELS:
        cas_id = target["casid"]
        print(f"\n--- Procesando Canal con CasId: {cas_id} ---")
        nombre_canal, logo_canal, cod_cadena_tv = obtener_datos_canal_csv(cas_id, CSV_URL)

        if not nombre_canal or not logo_canal or not cod_cadena_tv:
            print(f"ADVERTENCIA: No se pudieron obtener datos para CasId {cas_id}. Saltando.")
            continue
        channels_data[nombre_canal] = {"logo": logo_canal, "casid": cas_id}

        # Lista para acumular programas de los 3 días para este canal
        programas_combinados_canal = []

        # --- Bucle por cada fecha ---
        for date_str in date_strings:
            # Construir URL específica para el día
            # (Usaremos siempre el formato con fecha para consistencia)
            program_url = f"{BASE_PROGRAM_URL}{cod_cadena_tv}/{date_str}"
            print(f"INFO: Obteniendo lista inicial de programas desde: {program_url} (Fecha: {date_str})")

            # Obtener programación para ese día específico
            lista_programas_dia = obtener_programacion_movistar(program_url, nombre_canal)

            if lista_programas_dia:
                # Añadir los programas de este día a la lista combinada
                programas_combinados_canal.extend(lista_programas_dia)
            else:
                print(f"ADVERTENCIA: No se encontró programación para '{nombre_canal}' en la fecha {date_str}.")
        # --- Fin bucle por fecha ---

        # Guardar la lista combinada de los 3 días
        all_programs_processed[nombre_canal] = programas_combinados_canal
        print(f"INFO: Total programas acumulados para '{nombre_canal}' (3 días): {len(programas_combinados_canal)}")


    # 2. Obtener detalles (OG Title, Desc, Icon URL) para cada programa acumulado
    #    (Esta sección no necesita cambios lógicos, solo procesará más programas)
    print("\n--- Obteniendo detalles OG/Desc/Imagen para todos los programas (puede tardar MUCHO) ---")
    total_programas_a_detallar = sum(len(progs) for progs in all_programs_processed.values())
    prog_count = 0
    if total_programas_a_detallar == 0:
         print("INFO: No hay programas para obtener detalles.")
    else:
        print(f"INFO: Se intentarán obtener detalles para {total_programas_a_detallar} programas...")
        for nombre_canal, lista_programas in all_programs_processed.items():
            if not lista_programas: continue

            #print(f"INFO: Obteniendo detalles para {len(lista_programas)} programas de '{nombre_canal}'...")
            for programa in lista_programas:
                prog_count += 1
                prog_title_orig = programa.get('original_titulo', 'Desconocido')
                print(f"\rINFO: Prog {prog_count}/{total_programas_a_detallar} ('{prog_title_orig[:40]}...')", end="") # Progreso con \r
                if programa.get("detail_url"):
                    og_title, description, icon_url = obtener_detalles_programa(programa["detail_url"])
                    programa["og_titulo"] = og_title
                    programa["og_desc"] = description
                    programa["icon_url"] = icon_url
                    # Opcional: añadir un pequeño print si se encontró algo, pero \r lo borrará
                    # if og_title or description or icon_url: print(" -> D ", end="") else: print(" -> X ", end="")
                else:
                    programa["og_titulo"] = None; programa["og_desc"] = None; programa["icon_url"] = None
                    # print(" -> S ", end="") # Indica Sin URL

        print("\nINFO: Obtención de detalles finalizada.") # Nueva línea después del progreso con \r


    # 3. Generar el XML (sin cambios lógicos)
    if not channels_data:
         print("ERROR FATAL: No se pudieron obtener datos para ningún canal. Abortando.")
         exit(1)

    print("\n--- Generando archivo XML combinado (3 días) ---")
    fecha_actual = datetime.now().strftime("%d/%m/%Y %H:%M")
    root = ET.Element("tv", attrib={"generator-info-name": f"MultiPopUps 3 Dias {fecha_actual}"})

    # Crear <channel> (sin cambios)
    for nombre_canal, data in channels_data.items():
        channel_elem = ET.SubElement(root, "channel", attrib={"id": nombre_canal})
        ET.SubElement(channel_elem, "display-name").text = nombre_canal
        ET.SubElement(channel_elem, "icon", attrib={"src": data["logo"]})
    print(f"INFO: Añadidos {len(channels_data)} canales al XML.")

    # Crear <programme> (sin cambios lógicos, procesará la lista acumulada)
    programas_agregados_xml = 0
    for nombre_canal, lista_programas in all_programs_processed.items():
        if nombre_canal in channels_data:
            print(f"INFO: Añadiendo {len(lista_programas)} programas procesados para '{nombre_canal}'...")
            for prog_data in lista_programas:
                # Validar que tenemos inicio y fin antes de añadir
                if not prog_data.get("inicio") or not prog_data.get("stop"):
                     # Corrección: La clave de fin es 'fin', no 'stop' en nuestra estructura
                     if not prog_data.get("inicio") or not prog_data.get("fin"):
                        print(f"ADVERTENCIA: Programa '{prog_data.get('original_titulo')}' omitido por falta de hora de inicio/fin.")
                        continue

                programme_elem = ET.SubElement(root, "programme", attrib={
                    "start": prog_data["inicio"],
                    "stop": prog_data["fin"],
                    "channel": nombre_canal
                })
                final_title = prog_data.get("og_titulo") or prog_data.get("original_titulo") or "Título no disponible"
                ET.SubElement(programme_elem, "title", attrib={"lang": "es"}).text = final_title
                final_desc = prog_data.get("og_desc") or "(Descripción no disponible)"
                ET.SubElement(programme_elem, "desc", attrib={"lang": "es"}).text = final_desc
                icon_url = prog_data.get("icon_url")
                if icon_url:
                    ET.SubElement(programme_elem, "icon", attrib={"src": icon_url})
                programas_agregados_xml += 1

    print(f"INFO: Total de {programas_agregados_xml} programas añadidos al XML.")

    # 4. Escribir el archivo XML formateado (sin cambios)
    try:
        xml_str_formatted = prettify_xml(root)
        with open(OUTPUT_XML_FILE, "w", encoding="UTF-8") as f:
            f.write(xml_str_formatted)
        print(f"INFO: Archivo XML generado exitosamente: '{OUTPUT_XML_FILE}'")
    except Exception as e:
        print(f"ERROR: No se pudo escribir el archivo XML: {e}")

    end_time = time.time()
    print(f"--- Proceso finalizado en {end_time - start_time:.2f} segundos ---")