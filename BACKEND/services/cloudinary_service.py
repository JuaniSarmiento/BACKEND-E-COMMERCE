# En BACKEND/services/cloudinary_service.py

import cloudinary
import cloudinary.uploader
import os
from dotenv import load_dotenv
from fastapi import HTTPException, UploadFile, status
from typing import List

# Carga las variables de entorno del .env
load_dotenv()

# --- Configuración de Cloudinary ---
# Se configura automáticamente al leer las variables de entorno
cloudinary.config(
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key = os.getenv("CLOUDINARY_API_KEY"),
    api_secret = os.getenv("CLOUDINARY_API_SECRET"),
    secure=True # Para que siempre devuelva URLs https
)

async def upload_images(files: List[UploadFile]) -> List[str]:
    """
    Sube una lista de archivos a Cloudinary y devuelve sus URLs seguras.
    """
    uploaded_urls = []
    for file in files:
        try:
            # La magia de verdad pasa acá. `upload` es una función bloqueante,
            # pero para este caso de uso inicial no necesitamos complicarnos con hilos.
            # FastAPI es lo suficientemente inteligente para manejarlo bien.
            upload_result = cloudinary.uploader.upload(
                file.file,
                folder="void_ecommerce_products", # Carpeta dentro de Cloudinary
                resource_type="image"
            )
            # De la respuesta de Cloudinary, solo nos interesa la URL segura
            uploaded_urls.append(upload_result.get("secure_url"))
        except Exception as e:
            # Si una imagen falla, paramos todo y avisamos
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error al subir la imagen '{file.filename}': {e}"
            )
    return uploaded_urls