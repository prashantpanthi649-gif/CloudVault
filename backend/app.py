
import os
import re
from io import BytesIO
from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_file, send_from_directory
from pymongo import MongoClient
from dotenv import load_dotenv
from bson import ObjectId
from werkzeug.utils import secure_filename
from flask_cors import CORS

from s3_storage import (
    upload_file as s3_upload,
    download_file as s3_download,
    delete_file as s3_delete,
    copy_file as s3_copy
)

# Load environment variables
load_dotenv()

# Connect to MongoDB
client = MongoClient(os.getenv("MONGO_URI"))
db = client["CloudVaultDB"]
files_collection = db["files"]

app = Flask(__name__)
CORS(app)

# Keep local storage available for older uploaded files
UPLOAD_FOLDER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "uploads"
)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.route("/")
def home():
    return jsonify({
        "message": "Welcome to CloudVault!",
        "status": "Backend is running",
        "file_storage": "AWS S3"
    })


# GET: Retrieve all files
@app.route("/api/files", methods=["GET"])
def get_files():
    files = list(files_collection.find())

    for file in files:
        file["_id"] = str(file["_id"])

    return jsonify(files)


# GET: Retrieve one file's information
@app.route("/api/files/<file_id>", methods=["GET"])
def get_file(file_id):
    if not ObjectId.is_valid(file_id):
        return jsonify({"error": "Invalid file ID"}), 400

    file = files_collection.find_one({
        "_id": ObjectId(file_id)
    })

    if file is None:
        return jsonify({"error": "File not found"}), 404

    uploaded_at = file.get("uploaded_at")

    return jsonify({
        "id": str(file["_id"]),
        "name": file.get("name"),
        "type": file.get("type"),
        "size_bytes": file.get("size_bytes", 0),
        "uploaded_at": (
            uploaded_at.isoformat()
            if isinstance(uploaded_at, datetime)
            else None
        ),
        "storage": file.get("storage", "metadata-only")
    })


# GET: Search files
@app.route("/api/files/search", methods=["GET"])
def search_files():
    name = request.args.get("name", "")

    files = list(files_collection.find({
        "name": {
            "$regex": re.escape(name),
            "$options": "i"
        }
    }))

    for file in files:
        file["_id"] = str(file["_id"])

    return jsonify(files)


# GET: Filter files by type
@app.route("/api/files/filter", methods=["GET"])
def filter_files():
    file_type = request.args.get("type", "")

    files = list(files_collection.find({
        "type": {
            "$regex": f"^{re.escape(file_type)}$",
            "$options": "i"
        }
    }))

    for file in files:
        file["_id"] = str(file["_id"])

    return jsonify(files)


# GET: Calculate storage usage
@app.route("/api/storage", methods=["GET"])
def storage_usage():

    total_files = files_collection.count_documents({
        "storage": {"$in": ["local", "s3"]}
    })

    storage_data = list(files_collection.aggregate([
        {
            "$match": {
                "storage": {"$in": ["local", "s3"]}
            }
        },
        {
            "$group": {
                "_id": None,
                "total_bytes": {"$sum": "$size_bytes"}
            }
        }
    ]))

    total_bytes = (
        storage_data[0]["total_bytes"]
        if storage_data else 0
    )

    return jsonify({
        "total_files": total_files,
        "total_storage_bytes": total_bytes,
        "total_storage_kb": round(total_bytes / 1024, 2),
        "total_storage_mb": round(
            total_bytes / (1024 * 1024), 2
        )
    })


# POST: Upload an actual file to S3
@app.route("/api/upload", methods=["POST"])
def upload_file():

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    filename = secure_filename(file.filename)

    if not filename:
        return jsonify({"error": "Invalid filename"}), 400

    # Prevent duplicate filenames in the application
    if files_collection.find_one({"name": filename}):
        return jsonify({"error": "File already exists"}), 409

    # Calculate file size without saving it locally
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)

    file_type = os.path.splitext(filename)[1].lower()
    upload_time = datetime.now(timezone.utc)

    # Generate a unique S3 object key
    file_id = ObjectId()
    s3_key = f"files/{file_id}/{filename}"

    try:
        # Upload actual file contents to S3
        s3_upload(file, s3_key)

        # Save metadata in MongoDB
        files_collection.insert_one({
            "_id": file_id,
            "name": filename,
            "type": file_type,
            "size_bytes": file_size,
            "uploaded_at": upload_time,
            "storage": "s3",
            "s3_key": s3_key
        })

    except Exception as error:
        # Remove uploaded S3 object if metadata insertion fails
        try:
            s3_delete(s3_key)
        except Exception:
            pass

        app.logger.exception("Upload failed: %s", error)

        return jsonify({
            "error": "File upload failed"
        }), 500

    return jsonify({
        "message": "File uploaded successfully!",
        "file_id": str(file_id),
        "name": filename,
        "type": file_type,
        "size_bytes": file_size,
        "uploaded_at": upload_time.isoformat(),
        "storage": "s3"
    }), 201


# POST: Add metadata-only record
@app.route("/api/files", methods=["POST"])
def add_file():
    new_file = request.get_json()

    if (
        not isinstance(new_file, dict)
        or not isinstance(new_file.get("name"), str)
        or not isinstance(new_file.get("type"), str)
        or not new_file["name"].strip()
        or not new_file["type"].strip()
    ):
        return jsonify({
            "error": "Valid name and type are required"
        }), 400

    new_file.pop("_id", None)
    new_file.pop("size_bytes", None)
    new_file.pop("uploaded_at", None)

    new_file["storage"] = "metadata-only"

    result = files_collection.insert_one(new_file)
    new_file["_id"] = str(result.inserted_id)

    return jsonify(new_file), 201


# PUT: Rename a file
@app.route("/api/files/<file_id>", methods=["PUT"])
def update_file(file_id):

    if not ObjectId.is_valid(file_id):
        return jsonify({"error": "Invalid file ID"}), 400

    updated_data = request.get_json()

    if not isinstance(updated_data, dict) or set(updated_data.keys()) != {"name"}:
        return jsonify({
            "error": "Only the filename can be updated"
        }), 400

    if not isinstance(updated_data["name"], str):
        return jsonify({"error": "Invalid filename"}), 400

    new_name = secure_filename(updated_data["name"])

    if not new_name:
        return jsonify({"error": "Invalid filename"}), 400

    file = files_collection.find_one({
        "_id": ObjectId(file_id)
    })

    if file is None:
        return jsonify({"error": "File not found"}), 404

    old_name = file["name"]

    if new_name != old_name and files_collection.find_one({
        "name": new_name,
        "_id": {"$ne": ObjectId(file_id)}
    }):
        return jsonify({"error": "Filename already exists"}), 409

    old_key = file.get("s3_key")
    new_key = None
    copied = False

    # Rename an S3 object by copying it to a new key
    if new_name != old_name and file.get("storage") == "s3":

        if not old_key:
            return jsonify({"error": "S3 key missing"}), 500

        new_key = (
            f"files/{file_id}/{new_name}"
        )

        try:
            s3_copy(old_key, new_key)
            copied = True

        except Exception:
            app.logger.exception("S3 copy failed")
            return jsonify({
                "error": "Could not rename file in S3"
            }), 500

    # Handle older files stored locally
    elif new_name != old_name and file.get("storage") == "local":

        old_path = os.path.join(
            app.config["UPLOAD_FOLDER"], old_name
        )
        new_path = os.path.join(
            app.config["UPLOAD_FOLDER"], new_name
        )

        if not os.path.isfile(old_path):
            return jsonify({"error": "Original file not found"}), 404

        if os.path.exists(new_path):
            return jsonify({"error": "Filename already exists"}), 409

        try:
            os.rename(old_path, new_path)
        except OSError:
            return jsonify({
                "error": "Physical file rename failed"
            }), 500

    try:
        update_fields = {
            "name": new_name,
            "type": os.path.splitext(new_name)[1].lower()
        }

        if copied:
            update_fields["s3_key"] = new_key

        files_collection.update_one(
            {"_id": ObjectId(file_id)},
            {"$set": update_fields}
        )

    except Exception:
        if copied:
            try:
                s3_delete(new_key)
            except Exception:
                pass

        return jsonify({
            "error": "Database update failed"
        }), 500

    # Delete old S3 object only after metadata update
    if copied:
        try:
            s3_delete(old_key)
        except Exception:
            app.logger.exception(
                "Old S3 object could not be deleted"
            )

    return jsonify({
        "message": "File renamed successfully!"
    })


# GET: Download a file
@app.route("/api/download/<filename>", methods=["GET"])
def download_file(filename):

    filename = secure_filename(filename)

    if not filename:
        return jsonify({"error": "Invalid filename"}), 400

    file = files_collection.find_one({
        "name": filename,
        "storage": {"$in": ["s3", "local"]}
    })

    if file is None:
        return jsonify({"error": "File not found"}), 404

    # Download from AWS S3
    if file.get("storage") == "s3":

        try:
            response = s3_download(file["s3_key"])

            return send_file(
                BytesIO(response["Body"].read()),
                as_attachment=True,
                download_name=filename
            )

        except Exception:
            app.logger.exception("S3 download failed")
            return jsonify({
                "error": "Could not download file from S3"
            }), 500

    # Support older locally stored files
    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename,
        as_attachment=True
    )


# DELETE: Delete file and metadata
@app.route("/api/files/<file_id>", methods=["DELETE"])
def delete_file(file_id):

    if not ObjectId.is_valid(file_id):
        return jsonify({"error": "Invalid file ID"}), 400

    file = files_collection.find_one({
        "_id": ObjectId(file_id)
    })

    if file is None:
        return jsonify({"error": "File not found"}), 404

    try:
        if file.get("storage") == "s3":
            s3_delete(file["s3_key"])

        elif file.get("storage") == "local":

            filename = secure_filename(file["name"])

            if not filename or filename != file["name"]:
                return jsonify({
                    "error": "Invalid stored filename"
                }), 400

            file_path = os.path.join(
                app.config["UPLOAD_FOLDER"],
                filename
            )

            if os.path.isfile(file_path):
                os.remove(file_path)

    except Exception:
        app.logger.exception("File deletion failed")
        return jsonify({
            "error": "Physical file deletion failed"
        }), 500

    try:
        files_collection.delete_one({
            "_id": ObjectId(file_id)
        })

    except Exception:
        return jsonify({
            "error": "Database deletion failed"
        }), 500

    return jsonify({
        "message": "File and metadata deleted successfully!"
    })


# Test MongoDB connection
@app.route("/api/test-db")
def test_db():
    try:
        client.admin.command("ping")

        return jsonify({
            "message": "MongoDB connected successfully!"
        })

    except Exception:
        return jsonify({
            "error": "MongoDB connection failed"
        }), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
