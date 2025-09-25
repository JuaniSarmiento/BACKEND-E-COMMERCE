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
    variant_in: product_schemas.VarianteProducto, # OJO: El schema de variante necesita un `producto_id` opcional o sacarlo de acá
    db: AsyncSession = Depends(get_db),
    current_admin: user_schemas.UserOut = Depends(auth_services.get_current_admin_user)
):
    product = await db.get(Producto, product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado")

    # Creamos un diccionario a partir del schema de entrada y le agregamos el ID del producto
    variant_data = variant_in.model_dump()
    variant_data['producto_id'] = product_id

    new_variant = VarianteProducto(**variant_data)
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
async def update_product(product_id: int, product_in: product_schemas.ProductUpdate, db: AsyncSession = Depends(get_db), current_admin: user_schemas.UserOut = Depends(auth_services.get_current_admin_user)):
    product_db = await db.get(Producto, product_id)
    if not product_db:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado")
    
    update_data = product_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(product_db, key, value)
    
    db.add(product_db)
    await db.commit()

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