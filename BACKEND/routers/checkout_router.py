# En backend/routers/checkout_router.py

import mercadopago
import os
import logging
import hmac
import hashlib
import json
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, exc as SQLAlchemyExceptions
from sqlalchemy.orm import joinedload

from schemas import cart_schemas
from database.database import get_db
from database.models import Orden, DetalleOrden, VarianteProducto, Producto
from services import email_service
from services import auth_services # Importamos el servicio de auth
from schemas import user_schemas # Y el schema de usuario
from schemas import admin_schemas
from typing import List
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/api/checkout", tags=["Checkout"])

# --- CONFIGURACIÓN DE LOGGING ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configura el SDK de Mercado Pago
sdk = mercadopago.SDK(os.getenv("MERCADOPAGO_TOKEN"))
MERCADOPAGO_WEBHOOK_SECRET = os.getenv("MERCADOPAGO_WEBHOOK_SECRET")
FRONTEND_URL = os.getenv("FRONTEND_URL")
BACKEND_URL = os.getenv("BACKEND_URL")

def verify_mercadopago_signature(request: Request, payload: bytes):
    if not MERCADOPAGO_WEBHOOK_SECRET:
        logger.warning("MERCADOPAGO_WEBHOOK_SECRET no está configurado. Omitiendo verificación.")
        return

    signature_header = request.headers.get('x-signature')
    if not signature_header:
        raise HTTPException(status_code=400, detail="x-signature header faltante")

    try:
        parts = {p.split('=')[0]: p.split('=')[1] for p in signature_header.split(',')}
        ts = parts.get('ts')
        v1 = parts.get('v1')

        if not ts or not v1:
            raise HTTPException(status_code=400, detail="Firma inválida.")

        data_id = request.query_params.get('data.id')
        if not data_id:
            data_id = json.loads(payload).get('data', {}).get('id')

        manifest = f"id:{data_id};request-id:{request.headers.get('x-request-id')};ts:{ts};"
        
        expected_signature = hmac.new(
            MERCADOPAGO_WEBHOOK_SECRET.encode(),
            msg=manifest.encode(),
            digestmod=hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected_signature, v1):
            raise HTTPException(status_code=400, detail="Firma inválida.")
        logger.info("Firma de MercadoPago verificada exitosamente.")
    except Exception as e:
        logger.error(f"Error al verificar la firma de Mercado Pago: {e}")
        raise HTTPException(status_code=400, detail="Firma inválida.")

@router.post("/create_preference")
async def create_preference(cart: cart_schemas.Cart, db: AsyncSession = Depends(get_db)):
    items = []
    for item_in_cart in cart.items:
        query = (
            select(VarianteProducto)
            .where(VarianteProducto.id == item_in_cart.variante_id)
            .options(joinedload(VarianteProducto.producto))
        )
        result = await db.execute(query)
        variante_db = result.scalars().first()
        
        if not variante_db:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Ítem con id {item_in_cart.variante_id} no encontrado.")
        if variante_db.cantidad_en_stock < item_in_cart.quantity:
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Stock insuficiente para {variante_db.producto.nombre}.")

        items.append({
            "id": str(variante_db.id), "title": variante_db.producto.nombre,
            "quantity": item_in_cart.quantity, "unit_price": float(variante_db.producto.precio),
            "currency_id": "ARS"
        })

    external_reference = cart.user_id or cart.guest_session_id
    if not external_reference:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El carrito debe tener un user_id o guest_session_id.")

    preference_data = {
        "items": items,
        "back_urls": {
            "success": f"{FRONTEND_URL}/payment/success",
            "failure": f"{FRONTEND_URL}/payment/failure",
            "pending": f"{FRONTEND_URL}/payment/pending"
        },
        # --- ¡ACÁ ESTÁ EL ARREGLO! ---
        # Eliminamos la línea "auto_return": "approved", que causaba el conflicto.
        "notification_url": f"{BACKEND_URL}/api/checkout/webhook",
        "external_reference": str(external_reference)
    }

    logger.info(f"Creando preferencia de MP con data: {preference_data}")
    
    try:
        preference_response = sdk.preference().create(preference_data)
        
        if "response" in preference_response and preference_response["response"]:
            preference = preference_response["response"]
            return {"preference_id": preference.get("id"), "init_point": preference.get("init_point")}
        else:
            error_message = preference_response.get("message", "Error desconocido de Mercado Pago.")
            logger.error(f"Error de Mercado Pago al crear preferencia: {error_message}")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Error de Mercado Pago: {error_message}")

    except Exception as e:
        logger.error(f"Excepción al crear la preferencia de Mercado Pago: {e}", exc_info=True)
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail="Error interno del servidor al procesar el pago.")


@router.post("/webhook")
async def mercadopago_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    
    body = await request.body()
    
    if not body:
        logger.warning("Webhook de MercadoPago recibido con body vacío.")
        return {"status": "ok", "reason": "Empty body, possibly a ping."}

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        logger.error("Error al decodificar el JSON del webhook de MercadoPago.")
        raise HTTPException(status_code=400, detail="JSON malformado.")

    verify_mercadopago_signature(request, body)
    
    if data.get("type") == "payment":
        payment_id = data.get("data", {}).get("id")
        if not payment_id:
            return {"status": "ignored", "reason": "No payment ID"}

        try:
            existing_order = await db.execute(
                select(Orden).filter(Orden.payment_id_mercadopago == str(payment_id))
            )
            if existing_order.scalars().first():
                logger.info(f"Webhook para payment_id {payment_id} ya fue procesado. Omitiendo.")
                return {"status": "ok", "reason": "Already processed"}

            payment_info_response = sdk.payment().get(payment_id)
            payment_info = payment_info_response["response"]

            if payment_info["status"] == "approved":
                logger.info(f"Pago aprobado! ID: {payment_id}. Procesando orden...")
                await save_order_and_update_stock(payment_info, db, str(payment_id))
                
        except Exception as e:
            logger.error(f"Error al procesar el webhook de Mercado Pago: {e}")
            return {"status": "error", "detail": str(e)}

    return {"status": "ok"}

async def save_order_and_update_stock(payment_info: dict, db: AsyncSession, payment_id: str):
    
    try:
        usuario_id = payment_info.get("external_reference")
        monto_total = payment_info.get("transaction_amount")
        
        new_order = Orden(
            usuario_id=usuario_id,
            monto_total=monto_total,
            estado="Completado",
            estado_pago="Aprobado",
            metodo_pago="MercadoPago",
            payment_id_mercadopago=payment_id
        )
        db.add(new_order)
        await db.flush()

        items_procesados = []
        for item in payment_info.get("additional_info", {}).get("items", []):
            variante_id = int(item.get("id"))
            cantidad_comprada = int(item.get("quantity"))
            precio_unitario = float(item.get("unit_price"))

            order_detail = DetalleOrden(
                orden_id=new_order.id,
                variante_producto_id=variante_id,
                cantidad=cantidad_comprada,
                precio_en_momento_compra=precio_unitario
            )
            db.add(order_detail)
            items_procesados.append({"id": variante_id, "cantidad": cantidad_comprada})

        for item in items_procesados:
            variante_id = item["id"]
            cantidad_comprada = item["cantidad"]

            result = await db.execute(
                select(VarianteProducto)
                .where(VarianteProducto.id == variante_id)
                .with_for_update()
            )
            variante_producto = result.scalars().first()
            
            if variante_producto:
                if variante_producto.cantidad_en_stock >= cantidad_comprada:
                    variante_producto.cantidad_en_stock -= cantidad_comprada
                    db.add(variante_producto)
                else:
                    raise Exception(f"Stock insuficiente para {variante_id}")
            else:
                raise Exception(f"Variante {variante_id} no encontrada")

        await db.commit()
        logger.info(f"Orden {new_order.id} guardada y stock actualizado exitosamente.")

    except SQLAlchemyExceptions.IntegrityError as e:
        logger.error(f"Error de Integridad de DB al guardar la orden: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Error de base de datos al guardar la orden.")
    except Exception as e:
        logger.error(f"Error al procesar la orden y stock: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al procesar la orden: {str(e)}")

@router.get("/my-orders", response_model=List[admin_schemas.Orden], summary="Obtener las órdenes del usuario actual")
async def get_my_orders(
    db: AsyncSession = Depends(get_db),
    current_user: user_schemas.UserOut = Depends(auth_services.get_current_user)
):
    """
    Devuelve un historial de todas las órdenes realizadas
    por el usuario actualmente autenticado.
    """
    # El ID del usuario lo sacamos del token, no de la URL, por seguridad
    user_mongo_id = current_user.id 
    
    # Buscamos en la DB SQL las órdenes que coincidan con ese ID de usuario de Mongo
    query = select(Orden).filter(Orden.usuario_id == user_mongo_id).order_by(Orden.creado_en.desc())
    result = await db.execute(query)
    orders = result.scalars().all()

    return orders