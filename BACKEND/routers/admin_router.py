# En BACKEND/routers/admin_router.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List
from schemas import admin_schemas, metrics_schemas, user_schemas
from database.database import get_db, get_db_nosql
from database.models import Gasto, Orden, DetalleOrden, VarianteProducto, Producto, Categoria
from services.auth_services import get_current_admin_user
from pymongo.database import Database
from bson import ObjectId
from sqlalchemy.orm import joinedload
router = APIRouter(
    prefix="/api/admin",
    tags=["Admin"],
    dependencies=[Depends(get_current_admin_user)] # ¡Perfecto! Esto protege todo el router.
)

# --- Endpoints de Gastos ---

@router.get("/expenses", response_model=List[admin_schemas.Gasto])
async def get_expenses(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Gasto))
    expenses = result.scalars().all()
    return expenses

@router.post("/expenses", response_model=admin_schemas.Gasto, status_code=201)
async def create_expense(gasto: admin_schemas.GastoCreate, db: AsyncSession = Depends(get_db)):
    new_expense = Gasto(**gasto.model_dump())
    db.add(new_expense)
    await db.commit()
    await db.refresh(new_expense)
    return new_expense

# --- Endpoints de Ventas ---

@router.get("/sales", response_model=List[admin_schemas.Orden])
async def get_sales(db: AsyncSession = Depends(get_db)):
    # Para que la respuesta sea completa, cargamos los detalles de cada orden
    result = await db.execute(
        select(Orden).options(joinedload(Orden.detalles))
    )
    sales = result.scalars().unique().all()
    return sales

@router.get("/sales/{order_id}", response_model=admin_schemas.Orden, summary="Obtener detalles de una orden específica")
async def get_sale_details(order_id: int, db: AsyncSession = Depends(get_db)):
    """
    Obtiene todos los detalles de una única orden, incluyendo los productos
    comprados en ella.
    """
    result = await db.execute(
        select(Orden)
        .where(Orden.id == order_id)
        .options(
            joinedload(Orden.detalles) # Cargamos los detalles de la orden
            .joinedload(DetalleOrden.variante_producto) # De cada detalle, cargamos la variante
            .joinedload(VarianteProducto.producto) # De cada variante, cargamos el producto padre
        )
    )
    order = result.scalars().unique().first()

    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Orden no encontrada")
    
    return order

@router.post("/sales", status_code=201)
async def create_manual_sale(sale_data: admin_schemas.ManualSaleCreate, db: AsyncSession = Depends(get_db)):
    total_calculado = 0
    # Verificamos el precio de cada variante y calculamos el total
    for item in sale_data.items:
        # Hacemos un join para acceder al precio del producto padre
        result = await db.execute(
            select(Producto.precio)
            .join(VarianteProducto)
            .where(VarianteProducto.id == item.variante_producto_id)
        )
        precio_producto = result.scalar_one_or_none()
        if not precio_producto:
            raise HTTPException(status_code=404, detail=f"Variante de producto con ID {item.variante_producto_id} no encontrada.")
        total_calculado += float(precio_producto) * item.cantidad

    new_order = Orden(
        usuario_id=sale_data.usuario_id,
        monto_total=total_calculado,
        estado=sale_data.estado,
        estado_pago="pagado" # Asumimos que una venta manual ya está pagada
    )
    db.add(new_order)
    await db.flush() # Para tener el new_order.id disponible para los detalles

    # Creamos los detalles de la orden
    for item in sale_data.items:
        # Re-calculamos el precio acá para asegurar consistencia
        result = await db.execute(
            select(Producto.precio)
            .join(VarianteProducto)
            .where(VarianteProducto.id == item.variante_producto_id)
        )
        precio_producto = result.scalar_one()
        
        order_detail = DetalleOrden(
            orden_id=new_order.id,
            variante_producto_id=item.variante_producto_id,
            cantidad=item.cantidad,
            precio_en_momento_compra=precio_producto
        )
        db.add(order_detail)

    await db.commit()
    await db.refresh(new_order)
    return {"message": "Venta manual registrada exitosamente", "order_id": new_order.id}

# --- AVISO: Los Endpoints de Productos se eliminaron de acá ---
# Ahora viven exclusivamente en `routers/products_router.py`,
# que ya tiene la protección para que solo los admins puedan usarlos.
# ¡Mucho más limpio y ordenado!

# --- Endpoints de Usuarios ---

@router.get("/users", response_model=List[user_schemas.UserOut])
async def get_users(db: Database = Depends(get_db_nosql)):
    users_cursor = db.users.find({})
    users_list = await users_cursor.to_list(length=None)
    return users_list

@router.put("/users/{user_id}/role", response_model=user_schemas.UserOut, summary="Actualizar rol de un usuario")
async def update_user_role(user_id: str, user_update: user_schemas.UserUpdateRole, db: Database = Depends(get_db_nosql)):
    """
    Actualiza el rol de un usuario específico por su ID.
    Permite promover a 'admin', degradar a 'user' o asignar cualquier otro rol.
    """
    try:
        object_id = ObjectId(user_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID de usuario inválido")

    # Verificamos que el usuario exista
    user = await db.users.find_one({"_id": object_id})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    # Actualizamos el documento
    await db.users.update_one(
        {"_id": object_id},
        {"$set": {"role": user_update.role}}
    )

    # Devolvemos el usuario actualizado para confirmar el cambio
    updated_user = await db.users.find_one({"_id": object_id})
    return user_schemas.UserOut(**updated_user)

# --- Endpoints de Métricas y Gráficos ---

@router.get("/metrics/kpis", response_model=metrics_schemas.KPIMetrics)
async def get_kpis(db: AsyncSession = Depends(get_db), db_nosql: Database = Depends(get_db_nosql)):
    total_revenue_result = await db.execute(select(func.sum(Orden.monto_total)))
    total_revenue = total_revenue_result.scalar_one_or_none() or 0.0

    total_orders_result = await db.execute(select(func.count(Orden.id)))
    total_orders = total_orders_result.scalar_one_or_none() or 0

    average_ticket = total_revenue / total_orders if total_orders > 0 else 0.0

    total_users = await db_nosql.users.count_documents({})

    total_expenses_result = await db.execute(select(func.sum(Gasto.monto)))
    total_expenses = total_expenses_result.scalar_one_or_none() or 0.0

    return metrics_schemas.KPIMetrics(
        total_revenue=float(total_revenue),
        average_ticket=float(average_ticket),
        total_orders=total_orders,
        total_users=total_users,
        total_expenses=float(total_expenses)
    )

@router.get("/metrics/products", response_model=metrics_schemas.ProductMetrics)
async def get_product_metrics(db: AsyncSession = Depends(get_db)):
    most_sold_product_result = await db.execute(
        select(Producto.nombre, func.sum(DetalleOrden.cantidad).label("total_sold"))
        .join(VarianteProducto, Producto.variantes)
        .join(DetalleOrden, VarianteProducto.detalles_orden)
        .group_by(Producto.nombre)
        .order_by(func.sum(DetalleOrden.cantidad).desc())
        .limit(1)
    )
    most_sold_product_data = most_sold_product_result.first()
    most_sold_product_name = most_sold_product_data.nombre if most_sold_product_data else "N/A"

    product_with_most_stock_result = await db.execute(
        select(Producto.nombre)
        .order_by(Producto.stock.desc())
        .limit(1)
    )
    product_with_most_stock_name = product_with_most_stock_result.scalar_one_or_none() or "N/A"

    category_with_most_products_result = await db.execute(
        select(Categoria.nombre, func.count(Producto.id).label("product_count"))
        .join(Producto, Categoria.productos)
        .group_by(Categoria.nombre)
        .order_by(func.count(Producto.id).desc())
        .limit(1)
    )
    category_with_most_products_data = category_with_most_products_result.first()
    category_with_most_products_name = category_with_most_products_data.nombre if category_with_most_products_data else "N/A"

    return metrics_schemas.ProductMetrics(
        most_sold_product=most_sold_product_name,
        product_with_most_stock=product_with_most_stock_name,
        category_with_most_products=category_with_most_products_name
    )

@router.get("/charts/sales-over-time", response_model=metrics_schemas.SalesOverTimeChart)
async def get_sales_over_time(db: AsyncSession = Depends(get_db)):
    sales_data = await db.execute(
        select(
            func.date(Orden.creado_en).label("fecha"),
            func.sum(Orden.monto_total).label("total")
        )
        .group_by(func.date(Orden.creado_en))
        .order_by(func.date(Orden.creado_en))
    )
    result = [metrics_schemas.SalesDataPoint(fecha=row.fecha, total=float(row.total)) for row in sales_data.all()]
    return metrics_schemas.SalesOverTimeChart(data=result)

@router.get("/charts/expenses-by-category", response_model=metrics_schemas.ExpensesByCategoryChart)
async def get_expenses_by_category(db: AsyncSession = Depends(get_db)):
    expenses_data = await db.execute(
        select(
            Gasto.categoria,
            func.sum(Gasto.monto).label("monto")
        )
        .group_by(Gasto.categoria)
        .order_by(func.sum(Gasto.monto).desc())
    )
    result = [metrics_schemas.ExpensesByCategoryDataPoint(categoria=row.categoria, monto=float(row.monto)) for row in expenses_data.all()]
    return metrics_schemas.ExpensesByCategoryChart(data=result)