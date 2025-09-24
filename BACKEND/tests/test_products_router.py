# En tests/test_products_router.py
import pytest
from httpx import AsyncClient
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import Producto, Categoria

@pytest.mark.asyncio
async def test_get_products(client: AsyncClient, test_product_sql: Producto):
    response = await client.get("/api/products/")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert data[0]['id'] == test_product_sql.id

@pytest.mark.asyncio
async def test_get_product_by_id(client: AsyncClient, test_product_sql: Producto):
    response = await client.get(f"/api/products/{test_product_sql.id}")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["id"] == test_product_sql.id
    assert data["nombre"] == test_product_sql.nombre

@pytest.mark.asyncio
async def test_get_product_by_id_not_found(client: AsyncClient):
    response = await client.get("/api/products/99999")
    assert response.status_code == status.HTTP_404_NOT_FOUND

@pytest.mark.asyncio
async def test_create_product_as_admin(admin_authenticated_client: AsyncClient, test_category: Categoria):
    product_data = {
        "nombre": "Producto Creado por Admin", "descripcion": "Una descripción nueva",
        "precio": 99.99, "sku": "SKU-ADMIN-CREATE-001", "stock": 50,
        "categoria_id": test_category.id  # <-- ¡USA LA CATEGORÍA REAL!
    }
    response = await admin_authenticated_client.post("/api/products/", json=product_data)
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["nombre"] == product_data["nombre"]

@pytest.mark.asyncio
async def test_create_product_as_user_forbidden(authenticated_client: AsyncClient, test_category: Categoria):
    product_data = { "nombre": "Intento", "precio": 1.0, "sku": "SKU-USER-002", "stock": 1, "categoria_id": test_category.id }
    response = await authenticated_client.post("/api/products/", json=product_data)
    assert response.status_code == status.HTTP_403_FORBIDDEN

@pytest.mark.asyncio
async def test_update_product_as_admin(admin_authenticated_client: AsyncClient, test_product_sql: Producto):
    update_data = {"precio": 15.99, "stock": 75}
    response = await admin_authenticated_client.put(f"/api/products/{test_product_sql.id}", json=update_data)
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["precio"] == update_data["precio"]

@pytest.mark.asyncio
async def test_update_product_not_found(admin_authenticated_client: AsyncClient):
    response = await admin_authenticated_client.put("/api/products/99999", json={"precio": 1.0})
    assert response.status_code == status.HTTP_404_NOT_FOUND

@pytest.mark.asyncio
async def test_delete_product_as_admin(admin_authenticated_client: AsyncClient, test_product_sql: Producto, db_sql: AsyncSession):
    response = await admin_authenticated_client.delete(f"/api/products/{test_product_sql.id}")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["message"] == "Product deleted successfully"
    product_in_db = await db_sql.get(Producto, test_product_sql.id)
    assert product_in_db is None

@pytest.mark.asyncio
async def test_delete_product_not_found(admin_authenticated_client: AsyncClient):
    response = await admin_authenticated_client.delete("/api/products/99999")
    assert response.status_code == status.HTTP_404_NOT_FOUND