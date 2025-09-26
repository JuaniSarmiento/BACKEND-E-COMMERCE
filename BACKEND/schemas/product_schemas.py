# En backend/schemas/product_schemas.py

from pydantic import BaseModel, Field
from typing import Optional, List

# --- Schema para las Variantes ---
class VarianteProducto(BaseModel):
    id: int
    producto_id: int
    tamanio: str
    color: str
    cantidad_en_stock: int

    class Config:
        from_attributes = True

class VarianteProductoCreate(BaseModel):
    tamanio: str
    color: str
    cantidad_en_stock: int

# --- Schema Base del Producto (VERSIÓN CORREGIDA Y DEFINITIVA) ---
class ProductBase(BaseModel):
    nombre: str
    # La descripción es un texto simple y opcional
    descripcion: Optional[str] = None
    precio: float
    sku: str
    
    # Las URLs de las imágenes son una LISTA de textos
    urls_imagenes: Optional[List[str]] = [] 
    
    material: Optional[str] = None
    talle: Optional[str] = None
    color: Optional[str] = None
    stock: int = Field(..., ge=0)
    categoria_id: int

# --- Schema para crear un producto ---
class ProductCreate(ProductBase):
    pass

# --- Schema para actualizar un producto (CORREGIDO) ---
class ProductUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    precio: Optional[float] = None
    sku: Optional[str] = None
    
    # urls_imagenes también es una lista acá
    urls_imagenes: Optional[List[str]] = None
    
    material: Optional[str] = None
    talle: Optional[str] = None
    color: Optional[str] = None
    stock: Optional[int] = Field(None, ge=0)
    categoria_id: Optional[int] = None

# --- Schema para mostrar un producto completo ---
class Product(ProductBase):
    id: int
    variantes: List[VarianteProducto] = []
    class Config:
        from_attributes = True