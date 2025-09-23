# En tests/test_products_router.py
import pytest
from httpx import AsyncClient
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import Producto

# Fixture 'test_product_sql' viene de conftest.py y crea un producto de prueba.

@pytest.mark.asyncio
async def test_get_products(client: AsyncClient, test_product_sql: Producto):
    """Prueba que se puede obtener una lista de productos."""
    response = await client.get("/api/products/")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, list)
    # Comprueba que el producto de la fixture está en la lista y tiene la estructura correcta
    found = any(p['id'] == test_product_sql.id for p in data)
    assert found
    product_from_response = next(p for p in data if p['id'] == test_product_sql.id)
    assert "urls_imagenes" in product_from_response
    assert "variantes" in product_from_response
    assert isinstance(product_from_response["variantes"], list)


@pytest.mark.asyncio
async def test_get_product_by_id(client: AsyncClient, test_product_sql: Producto):
    """Prueba que se puede obtener un producto por su ID."""
    response = await client.get(f"/api/products/{test_product_sql.id}")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["id"] == test_product_sql.id
    assert data["nombre"] == test_product_sql.nombre
    # Verificar los nuevos campos
    assert "urls_imagenes" in data
    assert data["urls_imagenes"] is None # La fixture no lo establece
    assert "variantes" in data
    assert data["variantes"] == [] # La fixture no crea variantes


@pytest.mark.asyncio
async def test_get_product_by_id_not_found(client: AsyncClient):
    """Prueba que obtener un ID inexistente devuelve 404."""
    non_existent_id = 9999
    response = await client.get(f"/api/products/{non_existent_id}")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"] == "Producto no encontrado"


@pytest.mark.asyncio
async def test_create_product_as_admin(admin_authenticated_client: AsyncClient):
    """Prueba que un admin puede crear un producto."""
    product_data = {
        "nombre": "Producto Creado por Admin",
        "descripcion": "Una descripción nueva",
        "precio": 99.99,
        "sku": "SKU-ADMIN-CREATE-001",
        "urls_imagenes": "http://example.com/image.jpg",
        "material": "Seda",
        "talle": "L",
        "color": "Rojo",
        "stock": 50,
        "categoria_id": 1
    }
    response = await admin_authenticated_client.post("/api/products/", json=product_data)
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["nombre"] == product_data["nombre"]
    assert data["sku"] == product_data["sku"]
    assert data["urls_imagenes"] == product_data["urls_imagenes"]
    assert "id" in data
    assert "variantes" in data
    assert data["variantes"] == []


@pytest.mark.asyncio
async def test_create_product_as_user_forbidden(authenticated_client: AsyncClient):
    """Prueba que un usuario normal no puede crear un producto."""
    product_data = {"nombre": "Intento de user", "precio": 1.0, "sku": "SKU-USER-002", "stock": 1, "categoria_id": 1}
    response = await authenticated_client.post("/api/products/", json=product_data)
    # El endpoint de admin devuelve 403 si el rol no es correcto
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_update_product_as_admin(admin_authenticated_client: AsyncClient, test_product_sql: Producto):
    """Prueba que un admin puede actualizar un producto, incluyendo los nuevos campos."""
    product_id = test_product_sql.id
    update_data = {
        "precio": 15.99,
        "stock": 75,
        "urls_imagenes": "http://example.com/new_image.jpg"
    }
    response = await admin_authenticated_client.put(
        f"/api/products/{product_id}", json=update_data
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["precio"] == update_data["precio"]
    assert data["stock"] == update_data["stock"]
    assert data["urls_imagenes"] == update_data["urls_imagenes"]
    # Verificar que los otros campos no cambiaron y que las variantes siguen ahí
    assert data["id"] == product_id
    assert data["nombre"] == test_product_sql.nombre
    assert "variantes" in data


@pytest.mark.asyncio
async def test_update_product_not_found(admin_authenticated_client: AsyncClient):
    """Prueba que no se puede actualizar un producto que no existe."""
    non_existent_id = 9999
    response = await admin_authenticated_client.put(
        f"/api/products/{non_existent_id}", json={"precio": 1.0}
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_delete_product_as_admin(admin_authenticated_client: AsyncClient, test_product_sql: Producto, db_sql: AsyncSession):
    """Prueba que un admin puede borrar un producto."""
    product_id = test_product_sql.id
    response = await admin_authenticated_client.delete(f"/api/products/{product_id}")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["message"] == "Product deleted successfully"

    # Verificar que el producto ya no está en la base de datos
    product_in_db = await db_sql.get(Producto, product_id)
    assert product_in_db is None


@pytest.mark.asyncio
async def test_delete_product_not_found(admin_authenticated_client: AsyncClient):
    """Prueba que no se puede borrar un producto que no existe."""
    non_existent_id = 9999
    response = await admin_authenticated_client.delete(f"/api/products/{non_existent_id}")
    assert response.status_code == status.HTTP_404_NOT_FOUND
