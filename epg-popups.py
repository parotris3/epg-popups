import requests
import csv
import io
import json
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime, date, timedelta
import time
from bs4 import BeautifulSoup
import pytz
import html
import re # Para extraer año y país

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
# Las funciones obtener_datos_canal_csv, formatear_fecha_xmltv,
# obtener_programacion_movistar (la parte de encontrar detail_url y original_titulo),
# y prettify_xml se mantienen como en la versión anterior.
# Asegúrate de tener sus definiciones completas y correctas aquí.

# --- COPIA AQUÍ LAS FUNCIONES COMPLETAS Y CORRECTAS ---
# def obtener_datos_canal_csv(...) -> nombre, logo, cod_cadena_tv
# def formatear_fecha_xmltv(...) -> str_fecha_xmltv | None
# def obtener_programacion_movistar(...) -> lista_programas (con original_titulo, detail_url, etc.)
# def prettify_xml(...) -> str_xml_formateado

# (Incluyo las definiciones de la última versión para completitud,
#  asegúrate de que son las que te funcionan)
def obtener_datos_canal_csv(cas_id_buscar, url):
    print(f"INFO: Obteniendo datos del canal con CasId {cas_id_buscar} desde {url}")
    try:
        response = requests.get(url, timeout=15); response.raise_for_status()
        try: decoded_text = response.content.decode('utf-8-sig')
        except UnicodeDecodeError: decoded_text = response.text
        csv_file = io.StringIO(decoded_text); reader = csv.reader(csv_file, delimiter=',', quotechar='"')
        header = next(reader)
        try:
            casid_index = header.index('CasId'); nombre_index = header.index('Nombre')
            logo_index = header.index('Logo'); cod_cadena_tv_index = header.index('CodCadenaTv')
        except ValueError as e: print(f"ERROR: Columna no encontrada: {e}"); return None, None, None
        max_index = max(casid_index, nombre_index, logo_index, cod_cadena_tv_index)
        for row in reader:
            if len(row) > max_index:
                if row[casid_index] == cas_id_buscar:
                    nombre = row[nombre_index]; logo = row[logo_index]; cod_cadena_tv = row[cod_cadena_tv_index]
                    if nombre and logo and cod_cadena_tv: return nombre, logo, cod_cadena_tv
                    else: print(f"ERROR: Datos incompletos para CasId {cas_id_buscar}"); return None, None, None
        print(f"ERROR: CasId {cas_id_buscar} no encontrado."); return None, None, None
    except Exception as e: print(f"ERROR en CSV: {e}"); return None, None, None

def formatear_fecha_xmltv(fecha_iso):
    try:
        if len(fecha_iso) > 6 and fecha_iso[-3] == ':': fecha_iso = fecha_iso[:-3] + fecha_iso[-2:]
        return datetime.fromisoformat(fecha_iso).strftime("%Y%m%d%H%M%S %z")
    except ValueError: return None

def obtener_programacion_movistar(url, canal_nombre_target):
    print(f"INFO: Obteniendo programación para '{canal_nombre_target}' desde {url}")
    programas = []
    try:
        # Extraer la fecha de la URL para construir las fechas completas
        date_match = re.search(r'/(\d{4}-\d{2}-\d{2})$', url)
        if not date_match:
            print(f"ERROR: No se pudo extraer la fecha de la URL: {url}")
            return []
        current_date_str = date_match.group(1)
        current_date_obj = datetime.strptime(current_date_str, '%Y-%m-%d').date()

        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')

        # 1. Encontrar todos los bloques de programas por su clase 'container_box'
        # Usamos una función lambda para que coincida aunque tenga más clases (ej. "container_box g_CN")
        program_blocks = soup.find_all('div', class_=lambda c: c and 'container_box' in c.split())
        
        if not program_blocks:
            print(f"ADVERTENCIA: No se encontró ningún bloque 'container_box' para '{canal_nombre_target}'.")
            return []

        # 2. Extraer la información "en bruto" de cada bloque
        parsed_items = []
        for block in program_blocks:
            link_tag = block.find('a', href=True)
            title_tag = block.find('li', class_='title')
            time_tag = block.find('li', class_='time')

            if link_tag and title_tag and time_tag:
                hora_inicio_str = time_tag.get_text(strip=True)  # "05:43"
                titulo = title_tag.get_text(strip=True)
                detail_url = link_tag.get('href', '')
                if detail_url.startswith('/'):
                    detail_url = f"https://www.movistarplus.es{detail_url}"

                # Construir el objeto datetime de inicio con la fecha y la zona horaria
                try:
                    hora, minuto = map(int, hora_inicio_str.split(':'))
                    dt_start = LOCAL_TIMEZONE.localize(datetime.combine(current_date_obj, datetime.min.time())).replace(hour=hora, minute=minuto)
                    
                    # Si el programa empieza de madrugada (ej. 00:00 a 06:00), es probable que pertenezca al día siguiente 
                    # en el contexto de la parrilla del día anterior. Hay que manejar esto si causa problemas,
                    # pero por ahora lo dejamos así ya que la web los lista en el día correcto.

                    parsed_items.append({
                        "original_titulo": titulo,
                        "dt_start": dt_start,
                        "canal_nombre": canal_nombre_target,
                        "detail_url": detail_url
                    })
                except ValueError:
                    print(f"ADVERTENCIA: Formato de hora inesperado '{hora_inicio_str}' para '{titulo}'.")
                    continue
        
        if not parsed_items:
            print(f"INFO: No se encontraron items de programa parseables para '{canal_nombre_target}'.")
            return []

        # 3. Deducir la hora de fin a partir del inicio del siguiente programa
        for i, prog in enumerate(parsed_items):
            dt_end = None
            if i + 1 < len(parsed_items):
                # La hora de fin es la hora de inicio del siguiente programa
                dt_end = parsed_items[i+1]['dt_start']
                
                # Comprobación por si el siguiente programa es del día siguiente (la parrilla cruza la medianoche)
                if dt_end < prog['dt_start']:
                    dt_end += timedelta(days=1)

            else:
                # Es el último programa listado. No podemos saber el fin. Lo omitimos para no tener datos incorrectos.
                print(f"ADVERTENCIA: No se puede determinar la hora de fin para el último programa del día: '{prog['original_titulo']}'. Se omitirá.")
                continue

            # Formatear fechas a XMLTV
            fecha_inicio_xmltv = prog['dt_start'].strftime("%Y%m%d%H%M%S %z")
            fecha_fin_xmltv = dt_end.strftime("%Y%m%d%H%M%S %z")

            programas.append({
                "original_titulo": prog['original_titulo'],
                "inicio": fecha_inicio_xmltv,
                "fin": fecha_fin_xmltv,
                "canal_nombre": prog['canal_nombre'],
                "detail_url": prog['detail_url']
            })

        print(f"INFO: Programación extraída para '{canal_nombre_target}'. Total: {len(programas)}")
        return programas

    except requests.exceptions.RequestException as e:
        print(f"ERROR en Programación URL {url}: {e}")
        return []
    except Exception as e:
        import traceback
        print(f"ERROR inesperado procesando programación para '{canal_nombre_target}': {e}")
        traceback.print_exc()
        return []

def prettify_xml(elem):
    rough_string = ET.tostring(elem, 'utf-8'); reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ", encoding="UTF-8").decode('utf-8')

# MODIFICADA: Función para extraer todos los detalles necesarios
def obtener_detalles_programa(detail_url):
    """
    Obtiene múltiples detalles desde la URL de la ficha de un programa.
    Devuelve un diccionario con los campos encontrados.
    """
    if not detail_url:
        return {}
    print(f"\nDEBUG: Procesando detalles completos para: {detail_url}")
    
    details = {
        'og_titulo': None, 'sinopsis': None, 'icon_url': None, 'categoria': None,
        'pais': None, 'año': None, 'calificacion': None, 'ratingValue': None,
        'bestRating': None, 'presenta': None, 'director': None, 'reparto': None,
        'guion': None, 'musica': None, 'produccion': None, 'productora': None
    }

    try:
        time.sleep(REQUEST_DELAY) # Ya definido en tu script
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(detail_url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')

        # --- Extracción de meta etiquetas (og:title y sinopsis de name="description") ---
        og_title_tag = soup.find('meta', property='og:title')
        if og_title_tag and og_title_tag.get('content'):
            details['og_titulo'] = og_title_tag['content'].strip()
            print(f"DEBUG: og:title = '{details['og_titulo']}'")

        desc_tag = soup.find('meta', attrs={'name': 'description'})
        if desc_tag and desc_tag.get('content'):
            full_description = html.unescape(desc_tag['content'].strip())
            separator = " - "
            separator_index = full_description.find(separator)
            if separator_index != -1:
                details['sinopsis'] = full_description[separator_index + len(separator):].strip()
                # print(f"DEBUG: Sinopsis (procesada) = '{details['sinopsis'][:50]}...'")
            else:
                details['sinopsis'] = full_description
                # print(f"DEBUG: Sinopsis (completa) = '{details['sinopsis'][:50]}...'")
        
        # --- NUEVA Extracción HTML para Categoria, Pais, Año, Calificacion ---
        # Buscar primero el <ul>. Los <p> relevantes son hermanos que le siguen.
        ul_info_movie = soup.find('ul', class_='list-info-movie')
        if ul_info_movie:
            print("DEBUG: <ul class='list-info-movie'> encontrado.")
            # El primer <p> hermano siguiente debería ser la categoría
            p_categoria = ul_info_movie.find_next_sibling('p')
            if p_categoria:
                details['categoria'] = p_categoria.get_text(strip=True)
                print(f"DEBUG: Categoria (desde p) = '{details['categoria']}'")
                
                # El segundo <p> hermano (hermano del p_categoria) debería ser País (Año)
                p_pais_ano = p_categoria.find_next_sibling('p')
                if p_pais_ano:
                    text_p_pais_ano = p_pais_ano.get_text(strip=True)
                    print(f"DEBUG: Pais/Año P (texto) = '{text_p_pais_ano}'")
                    match = re.search(r'^(.*?)\s*\((\d{4})\)$', text_p_pais_ano)
                    if match:
                        details['pais'] = match.group(1).strip()
                        details['año'] = match.group(2).strip()
                        print(f"DEBUG: País = '{details['pais']}', Año = '{details['año']}'")
                    else: # Si no hay año en paréntesis, asumir que todo es el país
                        details['pais'] = text_p_pais_ano
                        print(f"DEBUG: País (sin año en formato esperado) = '{details['pais']}'")
                else:
                    print("DEBUG: No se encontró el segundo <p> para País/Año.")
            else:
                print("DEBUG: No se encontró el primer <p> para Categoría.")
        else:
            print("ADVERTENCIA: <ul class='list-info-movie'> no encontrado.")

        # Calificación (dentro de <div class="moral">)
        moral_div = soup.find('div', class_='moral')
        if moral_div:
            print("DEBUG: <div class='moral'> encontrado.")
            # No es necesario buscar el h3 Calificación si la img está directamente en moral_div
            # y es la única o la identificable por su 'alt'.
            # El snippet muestra solo una img, asumimos que es la de calificación.
            img_cal = moral_div.find('img', alt=True) 
            if img_cal and img_cal.get('alt'):
                details['calificacion'] = img_cal['alt'].strip()
                print(f"DEBUG: Calificación (alt de img) = '{details['calificacion']}'")
            else:
                print("DEBUG: No se encontró <img> con 'alt' en <div class='moral'>.")
        else:
            print("ADVERTENCIA: <div class='moral'> no encontrado para Calificación.")
            
        # --- Extracción de Presentador, Guionista (como antes, ajustar si es necesario) ---
        presentador_h3 = soup.find('h3', class_="heading", string=re.compile(r'Presentador', re.IGNORECASE))
        if presentador_h3:
            p_presentador = presentador_h3.find_next_sibling('p')
            if p_presentador: details['presenta'] = p_presentador.get_text(strip=True)
        
        guionista_h3 = soup.find('h3', class_="heading", string=re.compile(r'Guionista', re.IGNORECASE))
        if guionista_h3:
            p_guionista = guionista_h3.find_next_sibling('p')
            if p_guionista:
                span_guionista = p_guionista.find('span')
                details['guion'] = span_guionista.get_text(strip=True) if span_guionista else p_guionista.get_text(strip=True)

        # --- Extracción de JSON-LD (como antes para rating, director, reparto, musica, produccion, productora, icon_url) ---
        def extract_names_from_json_list(data_list):
            # ... (función auxiliar igual que antes) ...
            if not data_list: return None
            names = []
            if not isinstance(data_list, list): data_list = [data_list]
            for entry in data_list:
                if isinstance(entry, dict) and 'name' in entry: names.append(entry['name'].strip())
                elif isinstance(entry, str): names.append(entry.strip())
            return ", ".join(names) if names else None

        scripts_jsonld = soup.find_all('script', type='application/ld+json')
        json_ld_data_found_main_block = False # Para no sobreescribir si ya encontramos un bloque principal
        for script in scripts_jsonld:
            try:
                data = json.loads(script.string)
                items_to_check = []
                if isinstance(data, dict): items_to_check.append(data)
                elif isinstance(data, list): items_to_check.extend(data)

                for item in items_to_check:
                    # Intentar procesar solo el bloque principal una vez para estos campos
                    # Esto es una heurística, puede que no siempre sea el primer bloque relevante
                    current_item_is_main_type = item.get("@type") in ["Movie", "TVEpisode", "TVSeries", "CreativeWork"]

                    if not json_ld_data_found_main_block or not current_item_is_main_type:
                        if current_item_is_main_type:
                            json_ld_data_found_main_block = True

                        if 'director' in item and not details.get('director'):
                             details['director'] = extract_names_from_json_list(item.get('director'))
                        if 'actor' in item and not details.get('reparto'):
                             details['reparto'] = extract_names_from_json_list(item.get('actor'))
                        if 'musicBy' in item and not details.get('musica'):
                             details['musica'] = extract_names_from_json_list(item.get('musicBy'))
                        if 'producer' in item and not details.get('produccion'):
                             details['produccion'] = extract_names_from_json_list(item.get('producer'))
                        if 'productionCompany' in item and not details.get('productora'):
                             details['productora'] = extract_names_from_json_list(item.get('productionCompany'))
                        
                        if 'aggregateRating' in item and isinstance(item['aggregateRating'], dict):
                            if 'ratingValue' in item['aggregateRating'] and not details.get('ratingValue'):
                                details['ratingValue'] = str(item['aggregateRating']['ratingValue'])
                            if 'bestRating' in item['aggregateRating'] and not details.get('bestRating'):
                                details['bestRating'] = str(item['aggregateRating']['bestRating'])
                        elif 'ratingValue' in item and not details.get('ratingValue'):
                             details['ratingValue'] = str(item.get('ratingValue'))

                        if 'image' in item and not details.get('icon_url'):
                            image_data = item['image']
                            if isinstance(image_data, str): details['icon_url'] = image_data
                            elif isinstance(image_data, dict) and image_data.get('@type') == 'ImageObject' and 'url' in image_data:
                                details['icon_url'] = image_data['url']
                            elif isinstance(image_data, list) and image_data:
                                first_image = image_data[0]
                                if isinstance(first_image, str): details['icon_url'] = first_image
                                elif isinstance(first_image, dict) and first_image.get('@type') == 'ImageObject' and 'url' in first_image:
                                    details['icon_url'] = first_image['url']
            except (json.JSONDecodeError, AttributeError):
                continue
        # --- Fin Extracción JSON-LD ---

        # Imprimir un resumen de lo encontrado para depuración final de esta función
        print(f"DEBUG FINAL detalles: Cat='{details.get('categoria')}', Pais='{details.get('pais')}', Año='{details.get('año')}', Calif='{details.get('calificacion')}'")
        # print(f"DEBUG FINAL detalles: Sinopsis='{str(details.get('sinopsis'))[:30]}...', Rating='{details.get('ratingValue')}/{details.get('bestRating')}', Director='{details.get('director')}', Icono='{details.get('icon_url') is not None}'")

        return details

    except requests.exceptions.RequestException as e:
        print(f"ERROR: No se pudo obtener la página de detalle {detail_url}: {e}")
        return details # Devuelve lo que se haya podido recoger hasta el momento
    except Exception as e:
        print(f"ERROR: Error inesperado al procesar la página de detalle {detail_url}: {e}")
        return details


# --- Script Principal ---
if __name__ == "__main__":
    print("--- Iniciando generación de EPG XML con descripciones completas (3 días) ---")
    print(f"ADVERTENCIA: Este proceso será MUY largo debido al scraping detallado.")
    start_time_global = time.time()

    channels_data = {}
    all_programs_processed = {}

    today = datetime.now(LOCAL_TIMEZONE).date()
    dates_to_process = [today + timedelta(days=i) for i in range(3)]
    date_strings = [d.strftime('%Y-%m-%d') for d in dates_to_process]
    print(f"INFO: Se procesarán las fechas: {', '.join(date_strings)}")

    for target in TARGET_CHANNELS:
        cas_id = target["casid"]
        print(f"\n--- Procesando Canal con CasId: {cas_id} ---")
        nombre_canal, logo_canal, cod_cadena_tv = obtener_datos_canal_csv(cas_id, CSV_URL)

        if not nombre_canal or not logo_canal or not cod_cadena_tv:
            print(f"ADVERTENCIA: Datos CSV incompletos para CasId {cas_id}. Saltando.")
            continue
        channels_data[nombre_canal] = {"logo": logo_canal, "casid": cas_id}
        programas_combinados_canal = []

        for date_str in date_strings:
            program_url = f"{BASE_PROGRAM_URL}{cod_cadena_tv}/{date_str}"
            print(f"INFO: Obteniendo lista de programas desde: {program_url} (Fecha: {date_str})")
            lista_programas_dia = obtener_programacion_movistar(program_url, nombre_canal)
            if lista_programas_dia:
                programas_combinados_canal.extend(lista_programas_dia)
            else:
                print(f"ADVERTENCIA: No se encontró programación para '{nombre_canal}' en {date_str}.")
        
        all_programs_processed[nombre_canal] = programas_combinados_canal
        print(f"INFO: Total programas acumulados para '{nombre_canal}' (3 días): {len(programas_combinados_canal)}")

    print("\n--- Obteniendo detalles completos para todos los programas (puede tardar HORAS) ---")
    total_programas_a_detallar = sum(len(progs) for progs in all_programs_processed.values())
    prog_count = 0
    if total_programas_a_detallar == 0:
         print("INFO: No hay programas para obtener detalles.")
    else:
        print(f"INFO: Se intentarán obtener detalles para {total_programas_a_detallar} programas...")
        for nombre_canal, lista_programas in all_programs_processed.items():
            if not lista_programas: continue
            for programa in lista_programas:
                prog_count += 1
                prog_title_orig = programa.get('original_titulo', 'Desconocido')
                print(f"\rINFO: Prog {prog_count}/{total_programas_a_detallar} ('{prog_title_orig[:35]}...')", end="")
                
                # Inicializar campos de detalle en el programa por si falla la obtención
                detalle_fields = ['og_titulo', 'sinopsis', 'icon_url', 'categoria', 'pais', 'año', 
                                  'calificacion', 'ratingValue', 'bestRating', 'presenta', 'director', 
                                  'reparto', 'guion', 'musica', 'produccion', 'productora']
                for field in detalle_fields:
                    programa[field] = None

                if programa.get("detail_url"):
                    # Aquí se actualiza el diccionario 'programa' directamente con los detalles
                    # devueltos por obtener_detalles_programa
                    fetched_details = obtener_detalles_programa(programa["detail_url"])
                    if fetched_details: # Si devuelve un diccionario (incluso con Nones)
                        programa.update(fetched_details)
                else:
                    print(" -> Sin URL detalle", end=" ") # Añadir espacio para que no se solape con el siguiente \r

        print("\nINFO: Obtención de detalles finalizada.")

    print("\n--- Generando archivo XML combinado (3 días) con descripciones completas ---")
    fecha_actual = datetime.now().strftime("%d/%m/%Y %H:%M")
    root = ET.Element("tv", attrib={"generator-info-name": f"MultiPopUps FullDesc {fecha_actual}"})

    for nombre_canal, data in channels_data.items():
        channel_elem = ET.SubElement(root, "channel", attrib={"id": nombre_canal})
        ET.SubElement(channel_elem, "display-name").text = nombre_canal
        ET.SubElement(channel_elem, "icon", attrib={"src": data["logo"]})
    print(f"INFO: Añadidos {len(channels_data)} canales al XML.")

    programas_agregados_xml = 0
    for nombre_canal, lista_programas in all_programs_processed.items():
        if nombre_canal in channels_data:
            print(f"INFO: Añadiendo {len(lista_programas)} programas para '{nombre_canal}'...")
            for prog_data in lista_programas:
                if not prog_data.get("inicio") or not prog_data.get("fin"):
                    print(f"ADVERTENCIA: Programa '{prog_data.get('original_titulo')}' omitido por falta de hora de inicio/fin.")
                    continue

                programme_elem = ET.SubElement(root, "programme", attrib={
                    "start": prog_data["inicio"], "stop": prog_data["fin"], "channel": nombre_canal
                })
                
                final_title = prog_data.get("og_titulo") or prog_data.get("original_titulo") or "Título no disponible"
                ET.SubElement(programme_elem, "title", attrib={"lang": "es"}).text = final_title

                # --- Construcción del <desc> ---
                desc_parts = []
                # Linea 1: %categoria% | %año% | %calificacion% | *%ratingValue%/%bestRating%
                line1_elements = []
                if prog_data.get('categoria'): line1_elements.append(prog_data['categoria'])
                #if prog_data.get('año'): line1_elements.append(prog_data['año'])
                if prog_data.get('calificacion'): line1_elements.append(prog_data['calificacion'])
                
                rating_val = prog_data.get('ratingValue')
                best_rat = prog_data.get('bestRating')
                if rating_val and best_rat: line1_elements.append(f"*{rating_val}/{best_rat}")
                elif rating_val: line1_elements.append(f"*{rating_val}") # Si solo hay ratingValue

                if line1_elements: desc_parts.append(" | ".join(line1_elements))

                # Sinopsis
                if prog_data.get('sinopsis'): desc_parts.append(f"· {prog_data['sinopsis']}")
                
                # Campos adicionales con etiqueta
                def add_labeled_part(label, key):
                    value = prog_data.get(key)
                    if value: desc_parts.append(f"· {label}: {value}")
                
                add_labeled_part("País", 'pais')
                add_labeled_part("Presenta", 'presenta')
                add_labeled_part("Director", 'director')
                add_labeled_part("Reparto", 'reparto')
                add_labeled_part("Guion", 'guion')
                add_labeled_part("Música", 'musica')
                add_labeled_part("Producción", 'produccion')
                add_labeled_part("Productora", 'productora')

                final_desc_text = "\n".join(desc_parts) if desc_parts else "(Información detallada no disponible)"
                ET.SubElement(programme_elem, "desc", attrib={"lang": "es"}).text = final_desc_text
                # --- Fin Construcción del <desc> ---

                icon_url = prog_data.get("icon_url")
                if icon_url:
                    ET.SubElement(programme_elem, "icon", attrib={"src": icon_url})
                
                programas_agregados_xml += 1

    print(f"INFO: Total de {programas_agregados_xml} programas añadidos al XML.")

    try:
        xml_str_formatted = prettify_xml(root)
        with open(OUTPUT_XML_FILE, "w", encoding="UTF-8") as f: f.write(xml_str_formatted)
        print(f"INFO: Archivo XML generado exitosamente: '{OUTPUT_XML_FILE}'")
    except Exception as e:
        print(f"ERROR: No se pudo escribir el archivo XML: {e}")

    end_time_global = time.time()
    print(f"--- Proceso finalizado en {end_time_global - start_time_global:.2f} segundos ---")

