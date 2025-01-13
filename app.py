from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Configuration for the app
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('SQL_CONNECTION_STRING', 'sqlite:///default.db')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'a_different_secret_key')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database and utilities
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

# Azure Blob Storage
BLOB_CONNECTION_STRING = os.getenv('BLOB_CONNECTION_STRING')
blob_service = BlobServiceClient.from_connection_string(BLOB_CONNECTION_STRING)
blob_container_name = "vids"

# Import and register routes
from models_and_routes import register_routes

# Pass app configuration to the routes
register_routes(app.config, db, bcrypt, blob_service, blob_container_name)
@app.route('/')
def home():
    return jsonify({'message': 'Welcome to the Video Sharing API'}), 200

if __name__ == '__main__':
    app.run(debug=True)
