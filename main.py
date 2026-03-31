from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from models import ServiceRequest
from datetime import datetime
import uuid

app = FastAPI(title="Golden HealthCare Service API")

#Temp storage, will be replaced with database integration
dashboard_db = []

#CORS Config Section
#Empty List will host frontend origins for CORS
origins = ["http://localhost:4200", "https://healthcare-web-client.vercel.app"]

app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["GET", "POST", "OPTIONS", "PATCH", "DELETE"], allow_headers=["*"])

#Deployment Config
#A simple root check for now
#will be updated later with more info of front and back end implementation
@app.get("/")
async def root():
    return {"message": "Welcome to Golden HealthCare Service API."}

#Endpoint for validation
#post request format as follows until more info from front and back end implementation
@app.get("/api/admin/dashboard")
async def get_dashboard_data():
    #Returning requests to be reviewed
    return {"count": len(dashboard_db), "requests": dashboard_db}

@app.patch("/api/admin/request/{request_id}")
async def update_request_status(request_id: str, new_status: str):
    for request in dashboard_db:
        if request.get("id") == request_id:
            request["status"] = new_status
            return {"success": True, "updated_request": request}
    raise HTTPException(status_code=404, detail="Request not found")

@app.delete("/api/admin/request/{request_id}")
async def delete_request(request_id: str):
    global dashboard_db
    initial_length = len(dashboard_db)
    dashboard_db = [req for req in dashboard_db if req.get("id") != request_id]

    if len(dashboard_db) < initial_length:
        return {"success": True, "message": f"Request with ID {request_id} deleted."}
    raise HTTPException(status_code=404, detail="Request not found")

@app.post("/api/service-request")
async def create_service_request(request: ServiceRequest):
    entry = request.dict()
    #Generate an ID if front end did not provide one
    if not entry.get("id"):
        entry["id"] = str(uuid.uuid4())
    dashboard_db.insert(0, entry) #to insert at the beginning
    return {"success": True, "id": entry["id"]}

    
