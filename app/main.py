from fastapi import FastAPI
from .database import engine
from .models import Base
from .routers import services
from app.routers import social_media

Base.metadata.create_all(bind=engine)

app = FastAPI()

app.include_router(social_media.router)

app.include_router(services.router)
from .routers import requests

app.include_router(requests.router)