from fastapi.middleware.cors import CORSMiddleware


from fastapi import FastAPI
from .database import engine
from .models import Base
from .routers import services
from app.routers import social_media





app = FastAPI()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)

app.include_router(social_media.router)

app.include_router(services.router)
from .routers import requests

app.include_router(requests.router)