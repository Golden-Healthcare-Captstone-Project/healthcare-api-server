# Golden Healthcare API Server

## Overview
This is the FastAPI backend for the Golden Healthcare project.
It connects to a PostgreSQL database and exposes REST endpoints for the frontend.

---

## How to Run Backend

1. Activate virtual environment:
   source venv/bin/activate

2. Install dependencies (if needed):
   pip install -r requirements.txt

3. Run the server:
   uvicorn app.main:app --reload

API will be available at:
http://127.0.0.1:8000

Swagger docs:
http://127.0.0.1:8000/docs

---

## Database Setup

Database: PostgreSQL  
Database name: healthcare_dev  

To seed initial services:
   python -m app.seed

---

## Available Endpoints

GET /services  
Returns all available services

POST /services  
Creates a new service

Example JSON body:
{
  "name": "Transportation Assistance",
  "description": "Provides transportation for seniors",
  "price": 25.0
}

---

## Frontend Integration

Frontend runs on:
http://localhost:4200

Backend base URL:
http://127.0.0.1:8000

Frontend should call:
http://127.0.0.1:8000/services

CORS is enabled for local development.

---

## Architecture Notes

- Backend handles all database access
- Frontend does NOT directly connect to PostgreSQL
- All communication happens via REST API
- Tokens and secrets are stored securely in environment variables