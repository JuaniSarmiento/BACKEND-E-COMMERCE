import os
import asyncio
import aiosmtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# --- Configuración de logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Carga de variables de entorno ---
load_dotenv()

EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))

# --- Verificación de configuración ---
if not all([EMAIL_SENDER, EMAIL_PASSWORD]):
    logger.critical("¡ERROR FATAL! Las variables de entorno EMAIL_SENDER o EMAIL_APP_PASSWORD no están configuradas. El servicio de email no funcionará.")

async def send_order_confirmation_email(payment_info: dict):
    """
    Construye y envía un email de confirmación de compra de forma asíncrona.
    """
    if not all([EMAIL_SENDER, EMAIL_PASSWORD]):
        logger.error("El servicio de email no está configurado para enviar la confirmación de compra.")
        return

    receiver_email = payment_info["payer"]["email"]
    
    message = MIMEMultipart("alternative")
    message["Subject"] = "¡Gracias por tu compra en VOID!"
    message["From"] = EMAIL_SENDER
    message["To"] = receiver_email

    text = f"¡Hola! Tu compra ha sido confirmada. El total es de ${payment_info['transaction_amount']}."
    
    html = f"""
    <html>
      <body>
        <div style="font-family: sans-serif; text-align: center; padding: 20px;">
          <h1 style="color: #333;">¡Gracias por tu compra en VOID!</h1>
          <p>Hola,</p>
          <p>Tu compra ha sido procesada exitosamente.</p>
          <p style="font-size: 1.2em; font-weight: bold;">Total: ${payment_info['transaction_amount']}</p>
          <p style="margin-top: 30px; font-size: 0.9em; color: #777;">Recibirás otro email con los detalles del envío pronto.</p>
          <p style="font-weight: bold; margin-top: 20px;">VOID Indumentaria</p>
        </div>
      </body>
    </html>
    """
    
    part1 = MIMEText(text, "plain")
    part2 = MIMEText(html, "html")
    message.attach(part1)
    message.attach(part2)

    try:
        await aiosmtplib.send(
            message,
            hostname=SMTP_SERVER,
            port=SMTP_PORT,
            start_tls=True,
            username=EMAIL_SENDER,
            password=EMAIL_PASSWORD,
        )
        logger.info(f"Email de confirmación enviado a {receiver_email}")
    except Exception as e:
        logger.error(f"Error al enviar email de confirmación a {receiver_email}: {e}", exc_info=True)

async def send_plain_email(receiver_email: str, subject: str, body: str):
    """
    Envía un email de texto plano de forma asíncrona.
    """
    if not all([EMAIL_SENDER, EMAIL_PASSWORD]):
        logger.error(f"El servicio de email no está configurado. No se pudo enviar email a {receiver_email}.")
        return

    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = EMAIL_SENDER
    message["To"] = receiver_email

    try:
        await aiosmtplib.send(
            message,
            hostname=SMTP_SERVER,
            port=SMTP_PORT,
            start_tls=True,
            username=EMAIL_SENDER,
            password=EMAIL_PASSWORD,
        )
        logger.info(f"Email enviado a {receiver_email} con asunto: {subject}")
    except Exception as e:
        logger.error(f"Error al enviar email a {receiver_email}: {e}", exc_info=True)


# Para probar el envío (ejecutar directamente este archivo)
if __name__ == "__main__":
    if not all([EMAIL_SENDER, EMAIL_PASSWORD]):
        print("Para probar, necesitás configurar EMAIL_SENDER y EMAIL_APP_PASSWORD en tu archivo .env")
    else:
        mock_payment_info = {
            "payer": {"email": "test@example.com"},
            "transaction_amount": 99.99
        }
        print("Enviando email de prueba...")
        asyncio.run(send_order_confirmation_email(mock_payment_info))
        print("Prueba finalizada.")