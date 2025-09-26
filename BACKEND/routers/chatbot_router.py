from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging

from schemas import chatbot_schemas
from services import ia_services as ia_service
from database.database import get_db
from database.models import ConversacionIA

router = APIRouter(prefix="/api/chatbot", tags=["Chatbot"])

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constante para limitar la cantidad de turnos de conversación que enviamos a la IA.
# 5 turnos = 10 mensajes (5 del usuario, 5 de la IA). Evita prompts gigantes.
CONTEXT_TURNS_LIMIT = 5


async def _handle_chat_exception(
    e: Exception,
    conversacion: ConversacionIA,
    db: AsyncSession,
    detail: str,
    status_code: int = 500
):
    error_msg = f"{detail}: {e}"
    logger.error(error_msg, exc_info=True)
    conversacion.respuesta = f"ERROR: {error_msg}"
    db.add(conversacion)
    await db.commit()
    raise HTTPException(status_code=status_code, detail=detail)


@router.post("/query", response_model=chatbot_schemas.ChatResponse)
async def handle_chat_query(query: chatbot_schemas.ChatQuery, db: AsyncSession = Depends(get_db)):
    """
    Endpoint robusto para consultas al chatbot.
    Maneja el historial y el contexto de forma inteligente.
    """
    # 1. Guardamos la nueva pregunta del usuario en la DB
    nueva_conversacion = ConversacionIA(
        sesion_id=query.sesion_id,
        prompt=query.pregunta,
        respuesta=""
    )
    db.add(nueva_conversacion)
    await db.commit()
    await db.refresh(nueva_conversacion)

    try:
        # 2. Obtenemos el historial completo de la sesión
        result = await db.execute(
            select(ConversacionIA)
            .filter(ConversacionIA.sesion_id == query.sesion_id)
            .order_by(ConversacionIA.creado_en)
        )
        full_db_history = result.scalars().all()

        # 3. Limitamos el historial a los últimos turnos para eficiencia
        limited_history = full_db_history[-(CONTEXT_TURNS_LIMIT * 2):]

        # 4. Preparamos el contexto y las instrucciones por separado
        catalog_context = await ia_service.get_catalog_from_db(db)
        system_prompt = ia_service.get_chatbot_system_prompt() # Solo la personalidad

        # 5. Llamamos al servicio de IA con los componentes bien definidos
        respuesta_ia = await ia_service.get_ia_response(
            system_prompt=system_prompt,
            catalog_context=catalog_context,
            chat_history=limited_history
        )

        # 6. Actualizamos la conversación en la DB con la respuesta final
        nueva_conversacion.respuesta = respuesta_ia
        db.add(nueva_conversacion)
        await db.commit()

        return chatbot_schemas.ChatResponse(respuesta=respuesta_ia)

    except ia_service.OpenRouterServiceError as e:
        await _handle_chat_exception(
            e, nueva_conversacion, db,
            detail="Error en el servicio de IA (OpenRouter).",
            status_code=503
        )
    except Exception as e:
        await _handle_chat_exception(
            e, nueva_conversacion, db,
            detail="Error interno en el chatbot.",
            status_code=500
        )