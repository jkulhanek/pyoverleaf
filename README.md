# PyOverleaf
Unofficial Python API to access Overleaf.

## Tasks
- [x] List projects
- [x] Download project as zip
- [x] List and download individual files/docs
- [x] Upload new files/docs
- [x] Delete files, create folders
- [x] Python CLI interface to access project files
- [ ] Move, rename files
- [ ] Create, delete, archive, rename projects
- [ ] Access/update comments, perform live changes
- [ ] Access/update profile details
- [ ] Robust login

## Getting started
Install the project by running:
```bash
pip install 'pyoverleaf[cli]'
```

Before using the API, make sure you are logged into overleaf in your default web browser.
Currently only Google Chrome and Mozila Firefox are supported: https://github.com/richardpenman/browsercookie
Test if everything is working by listing the projects:
```bash
pyoverleaf ls
```


## Python API
The low-level Python API provides a way to access Overleaf projects from Python.
The main entrypoint is the class `pyoverleaf.Api`

### Accessing projects
```python
import pyoverleaf

api = pyoverleaf.Api()

# Lists the projects
projects = api.get_projects()

# Download the project as a zip
project_id = projects[0].id
api.download_project(project_id, "project.zip")
```

### Managing project files
```python
import pyoverleaf

api = pyoverleaf.Api()
# Choose a project
project_id = projects[0].id

# Get project files
root_folder = api.project_get_files(project_id)

# Create new folder
new_folder = api.project_create_folder(project_id, root_folder.id, "new-folder")

# Upload new file to the newly created folder
file_bytes = open("test-image.jpg", "rb").read()
new_file = api.project_upload_file(project_id, new_folder.id, "file-name.jpg", file_bytes)

# Delete newly added folder containing the file
api.project_delete_entity(project_id, new_folder)
```

## Higher-level Python IO API
The higher-level Python IO API allows users to access the project files in a pythonic way.
The main entrypoint is the class `pyoverleaf.ProjectIO`

Here are some examples on how to use the API:
```python
import pyoverleaf

api = pyoverleaf.Api()
# Choose a project
project_id = projects[0].id

# Get project IO API
io = pyoverleaf.ProjectIO(api, project_id)

# Check if a path exists
exists = io.exists("path/to/a/file/or/folder")

# Create a directory
io.mkdir("path/to/new/directory", parents=True, exist_ok=True)

# Listing a directory
for entity in io.listdir("path/to/a/directory"):
    print(entity.name)

# Reading a file
with io.open("path/to/a/file", "r") as f:
    print(f.read())

# Creating a new file
with io.open("path/to/a/new/file", "w+") as f:
    f.write("new content")
```


## Using the CLI
The CLI provides a way to access Overleaf from the shell.
To get started, run `pyoverleaf --help` to list available commands and their arguments.

### Listing projects and files
```bash
# Listing projects
pyoverleaf ls

# Listing project files
pyoverleaf ls project-name

# Listing project files in a folder
pyoverleaf ls project-name/path/to/files
```

### Downloading existing projects
```bash
pyoverleaf download-project project-name output.zip
```

### Creating and deleting directories
```bash
# Creating a new directory (including parents)
pyoverleaf mkdir -p project-name/path/to/new/directory

# Deleting
pyoverleaf rm project-name/path/to/new/directory
```

### Reading and writing files
```bash
# Writing to a file
echo "new content" | pyoverleaf write project-name/path/to/file.txt

# Uploading an image
cat image.jpg | pyoverleaf write project-name/path/to/image.jpg

# Reading a file
pyoverleaf read project-name/path/to/file.txt
```