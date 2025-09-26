import asyncio
import imaplib
import email
import logging
import os
import sys
from email.utils import parseaddr
from functools import partial
from dotenv import load_dotenv

# --- Agrego ruta raíz del proyecto para importar módulos ---
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from services import ia_services, email_service
from database.database import AsyncSessionLocal

# --- Configuración y logging ---
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

IMAP_SERVER = "imap.gmail.com"
EMAIL_ACCOUNT = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")

# --- Verificación de configuración ---
if not all([EMAIL_ACCOUNT, EMAIL_PASSWORD]):
    logger.critical("¡ERROR FATAL! Las variables de entorno EMAIL_SENDER o EMAIL_APP_PASSWORD no están configuradas. El worker de emails no puede iniciar.")
    # Si no hay configuración, no tiene sentido continuar.
    # Usamos sys.exit() para detener la ejecución del script.
    sys.exit(1)

def get_email_body(msg):
    """Extrae cuerpo texto plano del email."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode('utf-8', 'ignore')
    return msg.get_payload(decode=True).decode('utf-8', 'ignore')

async def run_sync_in_thread(func, *args):
    """
    Función helper para ejecutar código bloqueante en un hilo separado
    y no congelar el programa principal.
    """
    loop = asyncio.get_running_loop()
    func_to_run = partial(func, *args)
    return await asyncio.to_thread(func_to_run)

async def process_emails():
    """Procesa emails no leídos, obtiene respuesta IA y contesta."""
    # Doble chequeo por si acaso, aunque el script ya debería haber terminado
    if not all([EMAIL_ACCOUNT, EMAIL_PASSWORD]):
        logger.error("El worker de emails no puede procesar correos porque no está configurado.")
        return

    mail = None
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        logger.info(f"Conectando a IMAP server como {EMAIL_ACCOUNT}...")
        await run_sync_in_thread(mail.login, EMAIL_ACCOUNT, EMAIL_PASSWORD)
        await run_sync_in_thread(mail.select, "inbox")
        
        _, data = await run_sync_in_thread(mail.search, None, "UNSEEN")
        mail_ids = data[0].split()

        if not mail_ids:
            logger.info("No hay emails nuevos.")
            return

        logger.info(f"Se encontraron {len(mail_ids)} emails nuevos.")

        async with AsyncSessionLocal() as db_session:
            for mail_id in mail_ids:
                try:
                    _, fetch_data = await run_sync_in_thread(mail.fetch, mail_id, "(RFC822)")
                    msg = email.message_from_bytes(fetch_data[0][1])

                    body = get_email_body(msg)
                    sender_email = parseaddr(msg["from"])[1]
                    subject = msg["subject"]

                    logger.info(f"Procesando email de: {sender_email} (Asunto: {subject})")

                    catalog = await ia_services.get_catalog_from_db(db_session)
                    system_prompt = ia_services.get_chatbot_system_prompt()
                    full_system_prompt = f"{system_prompt}\n\n{catalog}"

                    # Preparar historial vacío o con datos si corresponde
                    gemini_history = []  # si tenés historial, convertilo al formato esperado

                    # Llamada directa a la coroutine de IA (no usar run_sync_in_thread con coroutine)
                    try:
                        ai_response = await ia_services.get_gemini_response(full_system_prompt, gemini_history)
                    except Exception as e:
                        logger.exception("Error al obtener respuesta de IA dentro del worker")
                        ai_response = "Lo siento, no puedo procesar la respuesta de IA en este momento."

                    logger.info(f"Enviando respuesta generada por IA a {sender_email}...")
                    await email_service.send_plain_email(
                        sender_email,
                        f"Re: {subject}",
                        ai_response
                    )

                    await run_sync_in_thread(mail.store, mail_id, '+FLAGS', '\Seen')
                    logger.info(f"Email ID {mail_id.decode('utf-8')} marcado como leído.")

                except Exception as e:
                    logger.error(f"Error al procesar email ID {mail_id.decode('utf-8')}: {e}", exc_info=True)

    except imaplib.IMAP4.error as e:
        logger.error(f"Error de IMAP (verificá tus credenciales y la configuración de IMAP): {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Error en el ciclo principal del worker: {e}", exc_info=True)
    finally:
        if mail and mail.state == 'SELECTED':
            await run_sync_in_thread(mail.close)
        if mail:
            await run_sync_in_thread(mail.logout)
            logger.info("Desconexión de IMAP exitosa.")

async def main():
    logger.info("Iniciando worker de emails... Presiona CTRL+C para detener.")
    while True:
        try:
            await process_emails()
            logger.info("Esperando 2 minutos para el próximo chequeo...")
            await asyncio.sleep(120)
        except KeyboardInterrupt:
            logger.info("Deteniendo el worker de emails.")
            break

if __name__ == "__main__":
    # El chequeo de configuración al inicio del script se encarga de detenerlo
    # si no están las variables de entorno.
    asyncio.run(main())
