import os
import random
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError
from dotenv import load_dotenv

load_dotenv()

uri = os.environ.get("MONGODB_ATLAS_URI")
if not uri:
    print("MONGODB_ATLAS_URI not found in .env")
    exit(1)

client = MongoClient(uri, serverSelectionTimeoutMS=5000)
db = client.sihalink

names = [
    "Michael Odongo", "Lucy Akinyi", "James Kipchoge", "Robert Mwangi", 
    "Amina Hassan", "Zainab Hassan", "Samuel Kipchoge", "Cynthia Odera", 
    "Salma Patel", "George Mwangi", "Rose Kipchoge", "Ruth Onyango", 
    "David Kimani", "Oscar Kipketer", "Hanifa Mohamed", "Fatuma Ali",
    "John Ochieng", "Mary Wanjiku", "Peter Mutisya", "Grace Njoroge"
]

updated = 0

try:
    print("Connecting to MongoDB Atlas...")
    encounters = db.encounters.find({})
    for doc in encounters:
        patient_details = doc.get("patient_details", {})
        if "name" not in patient_details or not patient_details["name"]:
            patient_details["name"] = random.choice(names)
            db.encounters.update_one(
                {"_id": doc["_id"]},
                {"$set": {"patient_details": patient_details}}
            )
            updated += 1
    print(f"Updated {updated} records with patient names.")
except ServerSelectionTimeoutError:
    print("Error: Could not connect to MongoDB Atlas. Your IP address may not be whitelisted.")
except Exception as e:
    print(f"Error: {e}")
