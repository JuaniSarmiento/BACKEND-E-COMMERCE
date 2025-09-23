# En backend/routers/products_router.py

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload # <-- 1. IMPORTAR JOINEDLOAD
from typing import List, Optional

from schemas import product_schemas
from database.database import get_db
from database.models import Producto

from services import auth_services
from schemas import user_schemas


router = APIRouter(
    prefix="/api/products",
    tags=["Products"]
)

@router.get("/", response_model=List[product_schemas.Product])
async def get_products(
    db: AsyncSession = Depends(get_db),
    material: Optional[str] = Query(None, description="Filtrar por material del producto"),
    precio_max: Optional[float] = Query(None, alias="precio", description="Filtrar por precio máximo"),
    categoria_id: Optional[int] = Query(None, description="Filtrar por ID de categoría"),
    talle: Optional[str] = Query(None, description="Filtrar por talle del producto"),
    color: Optional[str] = Query(None, description="Filtrar por color del producto"),
    skip: int = Query(0, ge=0, description="Número de productos a saltar"),
    limit: int = Query(10, ge=1, le=100, description="Número de productos a devolver"),
    sort_by: Optional[str] = Query(None, description="Ordenar por campo (ej: 'precio_asc', 'precio_desc', 'nombre_asc')")
):
    """
    Obtiene una lista de todos los productos, con filtros, paginación y ordenamiento.
    """
    # 2. ACTUALIZAR LA CONSULTA PARA INCLUIR VARIANTES
    query = select(Producto).options(joinedload(Producto.variantes))

    # Filtros
    if material:
        query = query.where(Producto.material.ilike(f"%{material}%"))
    if precio_max:
        query = query.where(Producto.precio <= precio_max)
    if categoria_id:
        query = query.where(Producto.categoria_id == categoria_id)
    if talle:
        query = query.where(Producto.talle.ilike(f"%{talle}%"))
    if color:
        query = query.where(Producto.color.ilike(f"%{color}%"))

    # Ordenamiento
    if sort_by:
        if sort_by == "precio_asc":
            query = query.order_by(Producto.precio.asc())
        elif sort_by == "precio_desc":
            query = query.order_by(Producto.precio.desc())
        elif sort_by == "nombre_asc":
            query = query.order_by(Producto.nombre.asc())
        elif sort_by == "nombre_desc":
            query = query.order_by(Producto.nombre.desc())

    # Paginación
    query = query.offset(skip).limit(limit)

    result = await db.execute(query)
    products = result.scalars().unique().all() # Usar .unique() para evitar duplicados por el JOIN

    return products


@router.get("/{product_id}", response_model=product_schemas.Product)
async def get_product(product_id: int, db: AsyncSession = Depends(get_db)):
    """
    Obtiene el detalle de un solo producto por su ID.
    """
    # 3. ACTUALIZAR LA CONSULTA PARA INCLUIR VARIANTES
    query = select(Producto).options(joinedload(Producto.variantes)).filter(Producto.id == product_id)
    result = await db.execute(query)
    product = result.scalars().unique().first() # Usar .unique()

    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    return product

@router.post(
    "/",
    response_model=product_schemas.Product,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un nuevo producto (Solo Admins)"
)
async def create_product(
    product_in: product_schemas.ProductCreate,
    db: AsyncSession = Depends(get_db),
    current_admin: user_schemas.UserOut = Depends(auth_services.get_current_admin_user)
):
    """
    Crea un nuevo producto en la base de datos.
    Requiere autenticación de administrador.
    """
    existing_product_sku = await db.execute(
        select(Producto).filter(Producto.sku == product_in.sku)
    )
    if existing_product_sku.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe un producto con el SKU: {product_in.sku}"
        )

    new_product = Producto(**product_in.model_dump())

    db.add(new_product)
    await db.commit()
    # 4. REFRESCAR EL OBJETO PARA CARGAR RELACIONES (COMO LAS VARIANTES, SI SE AÑADIERAN AL CREAR)
    await db.refresh(new_product, attribute_names=['variantes'])

    # Para una respuesta completa, necesitamos recargar el objeto con sus relaciones
    query = select(Producto).options(joinedload(Producto.variantes)).filter(Producto.id == new_product.id)
    result = await db.execute(query)
    created_product = result.scalars().unique().first()

    return created_product

@router.put(
    "/{product_id}",
    response_model=product_schemas.Product,
    summary="Actualizar un producto (Solo Admins)"
)
async def update_product(
    product_id: int,
    product_in: product_schemas.ProductUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: user_schemas.UserOut = Depends(auth_services.get_current_admin_user)
):
    """
    Actualiza un producto existente en la base de datos por su ID.
    """
    # 1. Buscamos el producto que vamos a actualizar.
    product_db = await db.get(Producto, product_id)

    if not product_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Producto no encontrado"
        )

    # 2. Actualizamos los datos del objeto en memoria.
    update_data = product_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(product_db, key, value)
    
    db.add(product_db)
    await db.commit()

    # --- ¡ACÁ ESTÁ LA MAGIA ANTIPEREZA! ---
    # 3. En lugar de devolver el objeto viejo, lo volvemos a pedir a la BD,
    #    pero esta vez forzando que cargue las 'variantes' para la respuesta.
    query = select(Producto).options(joinedload(Producto.variantes)).filter(Producto.id == product_id)
    result = await db.execute(query)
    updated_product_for_response = result.scalars().unique().first()

    return updated_product_for_response

# --- NUEVO ENDPOINT DELETE ---
@router.delete(
    "/{product_id}",
    status_code=status.HTTP_200_OK,
    summary="Eliminar un producto (Solo Admins)"
)
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: user_schemas.UserOut = Depends(auth_services.get_current_admin_user)
):
    """
    Elimina un producto de la base de datos por su ID.
    Requiere autenticación de administrador.
    """
    # 1. Buscar el producto por ID
    product_db = await db.get(Producto, product_id)

    if not product_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Producto no encontrado"
        )

    # 2. Eliminar el producto
    await db.delete(product_db)
    await db.commit()

    # 3. Devolver mensaje de éxito (como espera el test)
    return {"message": "Product deleted successfully"}