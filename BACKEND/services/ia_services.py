import os
import logging
import httpx
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from dotenv import load_dotenv

from database.models import Producto, ConversacionIA

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuración de OpenRouter ---
API_KEY = os.getenv("OPENROUTER_API_KEY")
API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_NAME = os.getenv("OPENROUTER_MODEL", "mistralai/mistral-7b-instruct:free")
SITE_URL = os.getenv("YOUR_SITE_URL", "")
SITE_NAME = os.getenv("YOUR_SITE_NAME", "")

class OpenRouterServiceError(Exception):
    pass

# --- Funciones Helper ---
async def get_catalog_from_db(db: AsyncSession) -> str:
    # ... (esta función es idéntica, la omito por brevedad pero dejala en tu código)
    try:
        result = await db.execute(select(Producto))
        products = result.scalars().all()
        if not products: return "No hay productos disponibles en este momento."
        catalog_lines = ["--- CATÁLOGO DE PRODUCTOS DISPONIBLES ---"]
        for prod in products: catalog_lines.append(f"- {prod.nombre} | ${prod.precio} | {prod.descripcion}")
        catalog_lines.append("--- FIN DEL CATÁLOGO ---")
        return "\n".join(catalog_lines)
    except Exception as e:
        logger.error(f"Error al obtener el catálogo de la DB: {e}")
        return "Error al obtener el catálogo."


def get_chatbot_system_prompt() -> str:
    # Este prompt ahora es más simple, solo define la personalidad.
    return (
        "Eres Jarvis, un asistente de ventas experto para la tienda 'VOID'. "
        "Tu personalidad es amable, canchera y muy eficiente. Tuteá al cliente. "
        "Tus respuestas deben ser concisas (máximo 30 palabras). "
        "Nunca digas que eres una IA. Si te saludan, sé amable y ofrece ayuda. "
        "Usa la información del catálogo que se te proporciona para responder sobre productos. "
        "Si no sabes algo, dilo claramente sin inventar información."
    )

def _build_messages_for_openrouter(system_prompt: str, catalog_context: str, chat_history: List[ConversacionIA]) -> List[Dict[str, Any]]:
    """
    Construye la lista de mensajes de forma robusta.
    1. Define la personalidad (system).
    2. Inyecta el contexto del catálogo como un mensaje falso para que la IA lo "estudie".
    3. Agrega el historial de la conversación.
    """
    messages = [{"role": "system", "content": system_prompt}]

    # Inyectamos el catálogo como si fuera una instrucción inicial del usuario,
    # y hacemos que la IA lo "confirme". Esta técnica se llama "priming".
    context_message = (
        "Tengo una tienda y quiero que respondas preguntas sobre mis productos. "
        "Aquí está el catálogo que debes usar exclusivamente:\n"
        f"{catalog_context}"
    )
    messages.append({"role": "user", "content": context_message})
    messages.append({"role": "assistant", "content": "Entendido. Catálogo recibido. Estoy listo para responder preguntas sobre esos productos."})
    
    # Agregamos el historial real de la conversación
    for entry in chat_history:
        if entry.prompt:
            messages.append({"role": "user", "content": entry.prompt.strip()})
        # Agregamos la respuesta del asistente solo si existe y no es un error
        if entry.respuesta and not entry.respuesta.strip().startswith("ERROR:"):
            messages.append({"role": "assistant", "content": entry.respuesta.strip()})
            
    return messages


# --- Lógica Principal de la IA ---
async def get_ia_response(system_prompt: str, catalog_context: str, chat_history: List[ConversacionIA]) -> str:
    if not API_KEY:
        raise OpenRouterServiceError("No se encontró la OPENROUTER_API_KEY en el archivo .env")

    headers = { "Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json", "HTTP-Referer": SITE_URL, "X-Title": SITE_NAME }
    messages = _build_messages_for_openrouter(system_prompt, catalog_context, chat_history)
    body = { "model": MODEL_NAME, "messages": messages }

    try:
        logger.info(f"--- Enviando request a OpenRouter con el modelo: {MODEL_NAME} ---")
        async with httpx.AsyncClient() as client:
            response = await client.post(API_URL, headers=headers, json=body, timeout=40)

        if response.status_code != 200:
            logger.error(f"Error de OpenRouter: STATUS={response.status_code}, BODY={response.text}")
            raise OpenRouterServiceError(f"Error {response.status_code}: {response.text}")

        data = response.json()
        logger.info(f"--- RESPUESTA COMPLETA DE OPENROUTER: {data} ---")

        if data.get("choices") and data["choices"][0].get("message") and data["choices"][0]["message"].get("content"):
            ia_content = data['choices'][0]['message']['content'].strip()
            if ia_content:
                logger.info("Respuesta recibida y procesada exitosamente.")
                return ia_content

        logger.warning("OpenRouter devolvió una respuesta vacía o con formato inesperado.")
        return "Disculpá, no sé qué responder a eso. ¿Podrías reformular tu pregunta?"

    except Exception as e:
        logger.error(f"Error al llamar a OpenRouter: {e}", exc_info=True)
        raise OpenRouterServiceError(f"Error en la comunicación con OpenRouter: {e}")