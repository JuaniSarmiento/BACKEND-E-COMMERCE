# En backend/schemas/product_schemas.py

from pydantic import BaseModel, Field
from typing import Optional,List

# --- CAMBIO NUEVO: Schema para las Variantes ---
class VarianteProducto(BaseModel):
    id: int
    producto_id: int
    tamanio: str
    color: str
    cantidad_en_stock: int

    class Config:
        from_attributes = True

# Schema base del producto, con los campos comunes
class ProductBase(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    precio: float
    sku: str
    urls_imagenes: Optional[List[str]] = None # <-- Ahora es una lista de strings
    material: Optional[str] = None
    talle: Optional[str] = None
    color: Optional[str] = None
    stock: int = Field(..., ge=0) # Nuevo campo para el stock
    categoria_id: int

# Schema para crear un producto (todos los campos de ProductBase son requeridos)
class ProductCreate(ProductBase):
    pass

# Schema para actualizar un producto (todos los campos son opcionales)
class ProductUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    precio: Optional[float] = None
    sku: Optional[str] = None
    urls_imagenes: Optional[List[str]] = None # <-- También acá
    material: Optional[str] = None
    talle: Optional[str] = None
    color: Optional[str] = None
    stock: Optional[int] = Field(None, ge=0) # Nuevo campo para el stock
    categoria_id: Optional[int] = None

# Schema para mostrar un producto en la base de datos (incluye el id)
class Product(ProductBase):
    id: int
    variantes: List[VarianteProducto] = [] #CAMBIO NUEVO!!!
    class Config:
        from_attributes = True # Permite que Pydantic lea los datos desde un objeto de SQLAlchemy