
const API_URL = "/api";

// Load all files
async function loadFiles() {
    const fileList = document.getElementById("file-list");

    try {
        const response = await fetch(`${API_URL}/files`);

        if (!response.ok) {
            throw new Error("Could not retrieve files");
        }

        const files = await response.json();

        displayFiles(files);
        loadStorage();

    } catch (error) {
        fileList.textContent = "Unable to connect to CloudVault backend.";
        console.error(error);
    }
}


// Display files
function displayFiles(files) {
    const fileList = document.getElementById("file-list");

    fileList.replaceChildren();

    if (files.length === 0) {
        fileList.textContent = "No files found.";
        return;
    }

    files.forEach(file => {
        const item = document.createElement("div");
        item.className = "file-item";

        const info = document.createElement("div");
        info.className = "file-info";

        const name = document.createElement("h3");
        name.textContent = file.name;

        const details = document.createElement("p");
        details.textContent =
            `${file.type || "Unknown"} | ${formatSize(file.size_bytes || 0)}`;

        info.append(name, details);

        const actions = document.createElement("div");
        actions.className = "file-actions";

        // Download button for S3 and local files
        if (file.storage === "s3" || file.storage === "local") {
            const downloadButton = document.createElement("button");

            downloadButton.textContent = "Download";

            downloadButton.onclick = () => {
                window.location.href =
                    `${API_URL}/download/${encodeURIComponent(file.name)}`;
            };

            actions.appendChild(downloadButton);
        }

        // Delete button
        const deleteButton = document.createElement("button");

        deleteButton.textContent = "Delete";
        deleteButton.className = "delete-button";

        deleteButton.onclick = () => deleteFile(file._id);

        actions.appendChild(deleteButton);

        item.append(info, actions);
        fileList.appendChild(item);
    });
}


// Convert bytes into readable format
function formatSize(bytes) {
    if (bytes < 1024) {
        return `${bytes} Bytes`;
    }

    if (bytes < 1024 * 1024) {
        return `${(bytes / 1024).toFixed(2)} KB`;
    }

    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}


// Upload a file
async function uploadFile() {
    const input = document.getElementById("file-input");
    const file = input.files[0];

    if (!file) {
        alert("Please select a file first.");
        return;
    }

    const formData = new FormData();
    formData.append("file", file);

    try {
        const response = await fetch(`${API_URL}/upload`, {
            method: "POST",
            body: formData
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.error || "Upload failed");
        }

        alert("File uploaded successfully to AWS S3!");

        input.value = "";
        await loadFiles();

    } catch (error) {
        alert(error.message);
        console.error(error);
    }
}


// Delete a file
async function deleteFile(fileId) {
    if (!confirm("Are you sure you want to delete this file?")) {
        return;
    }

    try {
        const response = await fetch(`${API_URL}/files/${fileId}`, {
            method: "DELETE"
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.error || "Deletion failed");
        }

        alert("File deleted successfully!");

        await loadFiles();

    } catch (error) {
        alert(error.message);
        console.error(error);
    }
}


// Search files
async function searchFiles() {
    const searchValue =
        document.getElementById("search-input").value.trim();

    if (!searchValue) {
        loadFiles();
        return;
    }

    try {
        const response = await fetch(
            `${API_URL}/files/search?name=${encodeURIComponent(searchValue)}`
        );

        if (!response.ok) {
            throw new Error("Search failed");
        }

        const files = await response.json();

        displayFiles(files);

    } catch (error) {
        console.error(error);
    }
}


// Load storage information
async function loadStorage() {
    const storageElement = document.getElementById("storage-used");

    try {
        const response = await fetch(`${API_URL}/storage`);

        if (!response.ok) {
            throw new Error("Could not load storage information");
        }

        const data = await response.json();

        storageElement.textContent =
            `${data.total_storage_mb} MB used (${data.total_files} files)`;

    } catch (error) {
        storageElement.textContent = "Storage unavailable";
        console.error(error);
    }
}


// Connect buttons and search input
document.getElementById("upload-button")
    .addEventListener("click", uploadFile);

document.getElementById("search-input")
    .addEventListener("input", searchFiles);


// Load files when page opens
loadFiles();
