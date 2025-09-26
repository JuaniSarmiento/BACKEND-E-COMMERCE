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

# ¡CAMBIO 1: Usamos el servicio que ya tenías!
from services import ia_services, email_service
from database.database import AsyncSessionLocal

# --- Configuración (sin cambios) ---
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

IMAP_SERVER = "imap.gmail.com"
EMAIL_ACCOUNT = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")


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
    # Usamos partial para preparar la función con sus argumentos
    func_to_run = partial(func, *args)
    # asyncio.to_thread es la forma moderna y recomendada de hacer esto
    return await asyncio.to_thread(func_to_run)


async def process_emails():
    """Procesa emails no leídos, obtiene respuesta IA y contesta."""
    mail = None
    try:
        # --- CAMBIO 2: Operaciones bloqueantes de IMAP en hilos separados ---
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        await run_sync_in_thread(mail.login, EMAIL_ACCOUNT, EMAIL_PASSWORD)
        await run_sync_in_thread(mail.select, "inbox")
        
        # mail.search también es bloqueante
        _, data = await run_sync_in_thread(mail.search, None, "UNSEEN")
        mail_ids = data[0].split()

        if not mail_ids:
            logger.info("No hay emails nuevos.")
            return

        logger.info(f"Se encontraron {len(mail_ids)} emails nuevos.")

        async with AsyncSessionLocal() as db_session:
            for mail_id in mail_ids:
                try:
                    # mail.fetch es bloqueante
                    _, fetch_data = await run_sync_in_thread(mail.fetch, mail_id, "(RFC822)")
                    msg = email.message_from_bytes(fetch_data[0][1])

                    body = get_email_body(msg)
                    sender_email = parseaddr(msg["from"])[1]
                    subject = msg["subject"]

                    logger.info(f"Procesando email de: {sender_email}")

                    catalog = await ia_services.get_catalog_from_db(db_session)
                    system_prompt = ia_services.get_chatbot_system_prompt()
                    full_system_prompt = f"{system_prompt}\n\n{catalog}"
                    
                    gemini_history = []
                    
                    # ¡Ojo acá! La llamada a Gemini puede ser bloqueante
                    # La envolvemos también para estar seguros
                    ai_response = await run_sync_in_thread(
                        ia_services.get_gemini_response,
                        full_system_prompt,
                        gemini_history,
                        body
                    )

                    # --- CAMBIO 3: Usar tu email_service asíncrono ---
                    # Ya tenías un servicio perfecto para esto, ¡reutilicemos!
                    logger.info(f"Enviando respuesta a {sender_email}...")
                    await email_service.send_plain_email(
                        sender_email,
                        f"Re: {subject}",
                        ai_response
                    )

                    # mail.store es bloqueante
                    await run_sync_in_thread(mail.store, mail_id, '+FLAGS', '\\Seen')

                except Exception as e:
                    logger.error(f"Error al procesar email ID {mail_id}: {e}", exc_info=True)

    except Exception as e:
        logger.error(f"Error en el ciclo principal del worker: {e}", exc_info=True)
    finally:
        if mail:
            # mail.logout es bloqueante
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
    asyncio.run(main())