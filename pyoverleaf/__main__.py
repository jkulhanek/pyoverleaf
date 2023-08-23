import shutil
import sys
import click
from . import Api, ProjectIO


def _get_io_and_path(api, path):
    if "/" not in path:
        raise click.BadParameter("Path must be in the format <project>/<local path>.")
    projects = api.get_projects()
    if path.startswith("/"):
        path = path[1:]
    project, *path = path.split("/", 1)
    if not path:
        path = ""
    else:
        path = path[0]
    project_id = None
    for p in projects:
        if p.name == project:
            project_id = p.id
            break
    if project_id is None:
        raise FileNotFoundError(f"Project '{project}' not found.")
    io = ProjectIO(api, project_id)
    return io, path


@click.group()
def main():
    pass

@main.command("ls", help="List projects or files in a project")
@click.argument("path", type=str, default=".")
def list_projects_and_files(path):
    api = Api()
    projects = api.get_projects()
    if not path or path in {".", "/"}:
        print("\n".join(project.name for project in projects))
    else:
        if path.startswith("/"):
            path = path[1:]
        project, *path = path.split("/", 1)
        if not path:
            path = ""
        else:
            path = path[0]
        project_id = None
        for p in projects:
            if p.name == project:
                project_id = p.id
                break
        if project_id is None:
            raise FileNotFoundError(f"Project '{project}' not found.")
        io = ProjectIO(api, project_id)
        files = io.listdir(path)
        print("\n".join(files))

@main.command("mkdir", help="Create a directory in a project")
@click.option("-p", "--parents", is_flag=True, help="Create parent directories if they don't exist.")
@click.argument("path", type=str)
def make_directory(path, parents):
    api = Api()
    io, path = _get_io_and_path(api, path)
    io.mkdir(path, parents=parents, exist_ok=parents)


@main.command("read", help="Reads the file in a project and writes to the standard output")
@click.argument("path", type=str)
def read(path):
    api = Api()
    io, path = _get_io_and_path(api, path)
    with io.open(path, "rb") as f:
        shutil.copyfileobj(f, sys.stdout.buffer)

@main.command("write", help="Reads the standard input and writes to the file in a project")
@click.argument("path", type=str)
def write(path):
    api = Api()
    io, path = _get_io_and_path(api, path)
    with io.open(path, "wb+") as f:
        shutil.copyfileobj(sys.stdin.buffer, f)

@main.command("rm", help="Remove file or folder from a project")
@click.argument("path", type=str)
def remove(path):
    api = Api()
    io, path = _get_io_and_path(api, path)
    io.remove(path)

@main.command("download-project", help="Download project as a zip file to the specified path.")
@click.argument("project", type=str)
@click.argument("output_path", type=str)
def download_project(project, output_path):
    api = Api()
    projects = api.get_projects()
    project_id = None
    for p in projects:
        if p.name == project:
            project_id = p.id
            break
    if project_id is None:
        raise FileNotFoundError(f"Project '{project}' not found.")
    api.download_project(project_id, output_path)
    print("Project downloaded to " + output_path)


if __name__ == "__main__":
    main()
