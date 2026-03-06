from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from models import ServiceRequest
from datetime import datetime

app = FastAPI(title="Golden HealthCare Service API")

#CORS Config Section
#Empty List will host frontend origins for CORS
origins = ["http://localhost:4200", "https://healthcare-web-client.vercel.app"]

app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"])

#Deployment Config
#A simple root check for now
#will be updated later with more info of front and back end implementation
@app.get("/")
async def root():
    return {"message": "Welcome to Golden HealthCare Service API."}

#Endpoint for validation
#post request format as follows until more info from front and back end implementation
@app.post("/api/service-request")
async def create_service_request(request: ServiceRequest):
    print(f"Received validated request for: {request.patient_name}")
    return {"success" : True, "message": "Service request received and validated.", "received_data": request}
