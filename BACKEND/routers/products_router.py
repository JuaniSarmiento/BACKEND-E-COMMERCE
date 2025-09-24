# En backend/routers/products_router.py

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from typing import List, Optional

from services import auth_services
from schemas import product_schemas, user_schemas
from database.database import get_db
from database.models import Producto

router = APIRouter(
    prefix="/api/products",
    tags=["Products"]
)

# --- GET (Estos ya estaban bien) ---
@router.get("/", response_model=List[product_schemas.Product])
async def get_products(db: AsyncSession = Depends(get_db), material: Optional[str] = Query(None), precio_max: Optional[float] = Query(None, alias="precio"), categoria_id: Optional[int] = Query(None), talle: Optional[str] = Query(None), color: Optional[str] = Query(None), skip: int = Query(0, ge=0), limit: int = Query(10, ge=1, le=100), sort_by: Optional[str] = Query(None)):
    query = select(Producto).options(joinedload(Producto.variantes))
    # (Acá va toda tu lógica de filtros y ordenamiento que ya tenías)
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

# --- POST (CORREGIDO) ---
@router.post("/", response_model=product_schemas.Product, status_code=status.HTTP_201_CREATED, summary="Crear un nuevo producto (Solo Admins)")
async def create_product(product_in: product_schemas.ProductCreate, db: AsyncSession = Depends(get_db), current_admin: user_schemas.UserOut = Depends(auth_services.get_current_admin_user)):
    # ... (la lógica para chequear el SKU queda igual)
    existing_product_sku = await db.execute(select(Producto).filter(Producto.sku == product_in.sku))
    if existing_product_sku.scalars().first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Ya existe un producto con el SKU: {product_in.sku}")

    new_product = Producto(**product_in.model_dump())
    db.add(new_product)
    await db.commit()
    await db.refresh(new_product)

    # ¡LA MAGIA! En vez de devolver 'new_product', lo volvemos a buscar con todo cargado.
    query = select(Producto).options(joinedload(Producto.variantes)).filter(Producto.id == new_product.id)
    result = await db.execute(query)
    created_product = result.scalars().unique().first()
    return created_product

# --- PUT (CORREGIDO) ---
@router.put("/{product_id}", response_model=product_schemas.Product, summary="Actualizar un producto (Solo Admins)")
async def update_product(product_id: int, product_in: product_schemas.ProductUpdate, db: AsyncSession = Depends(get_db), current_admin: user_schemas.UserOut = Depends(auth_services.get_current_admin_user)):
    product_db = await db.get(Producto, product_id)
    if not product_db:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado")
    
    # ... (la lógica para actualizar los campos queda igual)
    update_data = product_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(product_db, key, value)
    
    db.add(product_db)
    await db.commit()

    # ¡LA MAGIA OTRA VEZ! Volvemos a buscar el producto para que la respuesta sea completa.
    query = select(Producto).options(joinedload(Producto.variantes)).filter(Producto.id == product_id)
    result = await db.execute(query)
    updated_product = result.scalars().unique().first()
    return updated_product

# --- DELETE (CORREGIDO para que coincida con tu test) ---
@router.delete("/{product_id}", status_code=status.HTTP_200_OK, summary="Eliminar un producto (Solo Admins)")
async def delete_product(product_id: int, db: AsyncSession = Depends(get_db), current_admin: user_schemas.UserOut = Depends(auth_services.get_current_admin_user)):
    product_db = await db.get(Producto, product_id)
    if not product_db:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Producto no encontrado")
    await db.delete(product_db)
    await db.commit()
    return {"message": "Product deleted successfully"}