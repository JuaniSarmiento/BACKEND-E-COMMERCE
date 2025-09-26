# En backend/routers/products_router.py

# --- IMPORTS ACTUALIZADOS ---
from fastapi import (
    APIRouter, Depends, HTTPException, Query, status, 
    File, UploadFile, Form
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from typing import List, Optional

# --- Tus Módulos y Servicios ---
from database.models import VarianteProducto, Producto
from services import auth_services, cloudinary_service # <-- ¡Importamos el nuevo servicio!
from schemas import product_schemas, user_schemas
from database.database import get_db
from fastapi import Form, File, UploadFile
import json


router = APIRouter(
    prefix="/api/products",
    tags=["Products"]
)

# --- GET (Estos ya estaban bien, no se tocan) ---
@router.get("/", response_model=List[product_schemas.Product])
async def get_products(db: AsyncSession = Depends(get_db), material: Optional[str] = Query(None), precio_max: Optional[float] = Query(None, alias="precio"), categoria_id: Optional[int] = Query(None), talle: Optional[str] = Query(None), color: Optional[str] = Query(None), skip: int = Query(0, ge=0), limit: int = Query(10, ge=1, le=100), sort_by: Optional[str] = Query(None)):
    query = select(Producto).options(joinedload(Producto.variantes))
    if material: query = query.where(Producto.material.ilike(f"%{material}%"))
    if precio_max: query = query.where(Producto.precio <= precio_max)
    if categoria_id: query = query.where(Producto.categoria_id == categoria_id)
    if talle: query = query.where(Producto.talle.ilike(f"%{talle}%"))
    if color: query = query.where(Producto.color.ilike(f"%{color}%"))
    if sort_by:
        if sort_by == "precio_asc": query = query.order_by(Producto.precio.asc())
        elif sort_by == "precio_desc": query = query.order_by(Producto.precio.desc())
        elif sort_by == "nombre_asc": query = query.order_by(Producto.nombre.asc())
        elif sort_by == "nombre_desc": query = query.order_by(Producto.nombre.desc())
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    products = result.scalars().unique().all()
    return products

@router.get("/{product_id}", response_model=product_schemas.Product)
async def get_product(product_id: int, db: AsyncSession = Depends(get_db)):
    query = select(Producto).options(joinedload(Producto.variantes)).filter(Producto.id == product_id)
    result = await db.execute(query)
    product = result.scalars().unique().first()
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return product

# --- POST DE VARIANTES (Este que agregaste lo dejamos como está) ---
@router.post(
    "/{product_id}/variants", 
    response_model=product_schemas.VarianteProducto, 
    status_code=status.HTTP_201_CREATED,
    summary="Añadir una nueva variante a un producto (Solo Admins)"
)
async def create_variant_for_product(
    product_id: int,
    # --- ¡ESTE ES EL ARREGLO! ---
    # Ahora le pedimos el schema correcto, que solo tiene los campos que manda el formulario.
    variant_in: product_schemas.VarianteProductoCreate, 
    db: AsyncSession = Depends(get_db),
    current_admin: user_schemas.UserOut = Depends(auth_services.get_current_admin_user)
):
    product = await db.get(Producto, product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado")

    # El resto de la lógica funciona perfecto con este cambio
    variant_data = variant_in.model_dump()
    
    new_variant = VarianteProducto(
        **variant_data,
        producto_id=product_id  # Agregamos el ID del producto que viene en la URL
    )

    db.add(new_variant)
    await db.commit()
    await db.refresh(new_variant)
    
    return new_variant

# --- POST PARA CREAR PRODUCTO (ACÁ ESTÁ LA MAGIA NUEVA) ---
@router.post("/", response_model=product_schemas.Product, status_code=status.HTTP_201_CREATED, summary="Crear un nuevo producto con imágenes (Solo Admins)")
async def create_product(
    # Recibimos los datos del producto como campos de formulario
    nombre: str = Form(...),
    descripcion: Optional[str] = Form(None),
    precio: float = Form(...),
    sku: str = Form(...),
    stock: int = Form(...),
    categoria_id: int = Form(...),
    material: Optional[str] = Form(None),
    talle: Optional[str] = Form(None),
    color: Optional[str] = Form(None),
    # Y acá recibimos la lista de archivos de imagen
    images: List[UploadFile] = File(..., description="Hasta 3 imágenes del producto"),
    db: AsyncSession = Depends(get_db),
    current_admin: user_schemas.UserOut = Depends(auth_services.get_current_admin_user)
):
    # 1. Verificación del SKU (esto queda igual)
    existing_product_sku = await db.execute(select(Producto).filter(Producto.sku == sku))
    if existing_product_sku.scalars().first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Ya existe un producto con el SKU: {sku}")

    # 2. Verificación de la cantidad de imágenes
    if len(images) > 3:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Se pueden subir como máximo 3 imágenes.")

    # 3. Subida de imágenes a Cloudinary
    image_urls = []
    if images and images[0].filename: # Chequeamos que no venga una lista vacía o con archivos sin nombre
        image_urls = await cloudinary_service.upload_images(images)

    # 4. Armado del objeto del producto con los datos del formulario y las URLs
    product_data = product_schemas.ProductCreate(
        nombre=nombre,
        descripcion=descripcion,
        precio=precio,
        sku=sku,
        stock=stock,
        categoria_id=categoria_id,
        material=material,
        talle=talle,
        color=color,
        urls_imagenes=image_urls  # Le pasamos la lista de URLs que nos devolvió Cloudinary
    )

    # 5. Guardado en la base de datos
    new_product = Producto(**product_data.model_dump())
    db.add(new_product)
    await db.commit()
    await db.refresh(new_product)

    # 6. Devolvemos el producto completo, con sus variantes (si las tuviera)
    query = select(Producto).options(joinedload(Producto.variantes)).filter(Producto.id == new_product.id)
    result = await db.execute(query)
    created_product = result.scalars().unique().first()
    return created_product

# --- PUT (CORREGIDO, sin cambios funcionales pero consistente) ---
@router.put("/{product_id}", response_model=product_schemas.Product, summary="Actualizar un producto (Solo Admins)")
async def update_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: user_schemas.UserOut = Depends(auth_services.get_current_admin_user),
    # Recibimos todos los campos como Form, igual que en create_product
    nombre: str = Form(...),
    descripcion: Optional[str] = Form(None),
    precio: float = Form(...),
    sku: str = Form(...),
    stock: int = Form(...),
    categoria_id: int = Form(...),
    material: Optional[str] = Form(None),
    talle: Optional[str] = Form(None),
    color: Optional[str] = Form(None),
    # Las imágenes nuevas son opcionales al editar
    images: List[UploadFile] = File(None),
    # Recibimos las URLs de las imágenes que ya existen como un texto
    existing_images_json: str = Form("[]")
):
    product_db = await db.get(Producto, product_id)
    if not product_db:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado")

    # 1. Subir las imágenes nuevas (si el admin mandó alguna)
    new_image_urls = []
    if images and images[0].filename:
        new_image_urls = await cloudinary_service.upload_images(images)

    # 2. Combinar las URLs viejas con las nuevas
    # (Acá podrías agregar lógica para eliminar imágenes, pero por ahora las sumamos)
    existing_urls = json.loads(existing_images_json)
    all_urls = existing_urls + new_image_urls

    # 3. Actualizamos el objeto de la base de datos campo por campo
    product_db.nombre = nombre
    product_db.descripcion = descripcion
    product_db.precio = precio
    product_db.sku = sku
    product_db.stock = stock
    product_db.categoria_id = categoria_id
    product_db.material = material
    product_db.talle = talle
    product_db.color = color
    product_db.urls_imagenes = all_urls

    db.add(product_db)
    await db.commit()
    await db.refresh(product_db)

    # Devolvemos el producto actualizado con todas sus relaciones cargadas
    query = select(Producto).options(joinedload(Producto.variantes)).filter(Producto.id == product_id)
    result = await db.execute(query)
    updated_product = result.scalars().unique().first()
    return updated_product

# --- DELETE (CORREGIDO, sin cambios funcionales pero consistente) ---
@router.delete("/{product_id}", status_code=status.HTTP_200_OK, summary="Eliminar un producto (Solo Admins)")
async def delete_product(product_id: int, db: AsyncSession = Depends(get_db), current_admin: user_schemas.UserOut = Depends(auth_services.get_current_admin_user)):
    product_db = await db.get(Producto, product_id)
    if not product_db:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado")
    await db.delete(product_db)
    await db.commit()
    return {"message": "Product deleted successfully"}