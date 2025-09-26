import os
from fastapi import APIRouter, HTTPException, status
from dotenv import load_dotenv
import mercadopago
from schemas.payment_schemas import CardToken

# Carga las variables de entorno del .env
load_dotenv()

# --- Configuración de Mercado Pago ---
access_token = os.getenv("MERCADOPAGO_TOKEN")
if not access_token:
    raise Exception("MERCADOPAGO_ACCESS_TOKEN no está configurado en las variables de entorno")

sdk = mercadopago.SDK(access_token)

router = APIRouter(
    prefix="/payments",
    tags=["Payments"]
)

@router.post("/process-payment", status_code=status.HTTP_200_OK)
async def process_payment(card_token: CardToken):
    """
    Procesa un pago utilizando un card_token generado por el frontend.
    """
    payment_data = {
        "transaction_amount": 100, # Monto de ejemplo, deberías pasarlo desde el frontend
        "token": card_token.token,
        "installments": 1,
        "payment_method_id": "visa", # Debería detectarse o pasarse desde el frontend
        "payer": {
            "email": "test_user@example.com" # Email del usuario, debería obtenerse de la sesión/token JWT
        }
    }

    try:
        payment_response = sdk.payment().create(payment_data)
        payment = payment_response["response"]

        if payment["status"] == "approved":
            return {"status": "approved", "payment_id": payment["id"]}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El pago no fue aprobado. Estado: {payment['status']} - {payment['status_detail']}"
            )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al procesar el pago: {e}"
        )
