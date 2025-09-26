# En BACKEND/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from database.database import engine
from database.models import Base
from routers import health_router, auth_router, products_router, cart_router, admin_router, chatbot_router, checkout_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Clean up the engine connection
    await engine.dispose()

app = FastAPI(
    title="VOID Backend - Finalizado",
    description="Backend con autenticación, catálogo de productos, carrito de compras, panel de admin y chatbot.",
    version="0.6.0",
    lifespan=lifespan
)

# --- INICIO DEL CAMBIO ---

# 1. Definimos la lista de "amigos" permitidos.
#    Por ahora, solo el servidor de desarrollo de Vite/React.
origins = [
    "http://localhost:5173",
]

# 2. Agregamos el middleware de CORS con la lista específica.
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # <-- Usamos nuestra lista en vez de ["*"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- FIN DEL CAMBIO ---

@app.get("/")
def home():
    return {"mensaje": "Backend de VOID funcionando (Sprint 6)."}

# Incluimos todos los routers
app.include_router(health_router.router)
app.include_router(auth_router.router)
app.include_router(products_router.router)
app.include_router(cart_router.router)
app.include_router(admin_router.router)
app.include_router(chatbot_router.router)
app.include_router(checkout_router.router)