import os
import pathlib
import io
from typing import Optional, Union, IO, List
from ._webapi import Api, ProjectFolder, ProjectFile


class ProjectBytesIO(io.BytesIO):
    def __init__(self, api: Api, project_id: str, file: Optional[ProjectFile] = None, mode: str = "r", update_file = None):
        self._api = api
        self._project_id = project_id
        self._file = file
        self._mode = mode
        self._update_file = update_file
        self._prefix_bytes = None
        init_bytes = b""
        if file is not None and "w" not in mode:
            init_bytes = self._api.project_download_file(self._project_id, self._file)
        if "a" in mode:
            self._prefix_bytes = init_bytes
            init_bytes = b""
        super().__init__(init_bytes)

    def writable(self) -> bool:
        return "w" in self._mode or "a" in self._mode or "+" in self._mode

    def readable(self) -> bool:
        return "r" in self._mode or "+" in self._mode

    def flush(self) -> None:
        super().flush()
        if self.writable():
            data = self.getvalue()
            if self._prefix_bytes is not None:
                data = self._prefix_bytes + data
            self._file = self._update_file(data)

    def close(self) -> None:
        self.flush()
        super().close()


class ProjectIO:
    def __init__(self, api: "Api", project_id: str):
        self._api = api
        self._project_id = project_id
        self._cached_project_files = None

    def _project_files(self) -> ProjectFolder:
        if self._cached_project_files is None:
            self._cached_project_files = self._api.project_get_files(self._project_id)
        return self._cached_project_files

    def _find(self, path: Union[pathlib.PurePath, str]) -> Union[ProjectFolder, ProjectFile, None]:
        current_pointer = self._project_files()
        path = pathlib.PurePath(path)
        for part in path.parts:
            for child in current_pointer.children:
                if child.name == part:
                    current_pointer = child
                    break
            else:
                return None
        return current_pointer

    def exists(self, path: Union[pathlib.PurePath, str]):
        """
        Check if a file exists in the project.

        :param path: The path to the file.
        :return: True if the file exists, else False.
        """
        return self._find(path) is not None

    def open(self, path: Union[pathlib.PurePath, str], mode: str = "r", encoding: Optional[str] = None) -> IO:
        """
        Open a file in the project.

        :param path: The path to the file.
        :param mode: The mode to open the file in.
        :param encoding: The encoding to use if the file is not opened in binary mode.
        :return: A file-like object.
        """
        assert mode in ["r", "w", "a", "r+", "w+", "a+", "rb", "wb", "ab", "rb+", "wb+", "ab+"]
        binary = False
        if "b" in mode:
            binary = True

        assert_file_exists = True
        if "r" in mode and "+" in mode:
            # Create file if it doesn't exist
            assert_file_exists = False
        elif "w" in mode:
            assert_file_exists = False

        # Find the handles
        parent_path = pathlib.PurePath(path).parent
        folder = self._project_files()
        for part in parent_path.parts:
            for child in folder.children:
                if child.name == part and child.type == "folder":
                    folder = child
                    break
            else:
                raise FileNotFoundError("No such file or directory: " + str(path))

        folder_id = folder.id
        file = None
        filename = os.path.split(path)[-1]
        for child in folder.children:
            if child.name == filename and child.type != "folder":
                file = child
                break
        if file is None and assert_file_exists:
            raise FileNotFoundError("No such file or directory: " + str(path))

        def update_file(data):
            return self._api.project_upload_file(self._project_id, folder_id, filename, data)

        bytes_io = ProjectBytesIO(self._api, self._project_id, file, mode, update_file)
        if not binary:
            return io.TextIOWrapper(bytes_io, encoding=encoding)
        return bytes_io

    def mkdir(self, path: Union[pathlib.PurePath, str], exist_ok: bool = False, *, parents: bool = False) -> None:
        """
        Create a directory in the project.

        :param path: The path to the directory.
        :param exist_ok: If True, no exception will be raised if the directory already exists.
        :param parents: If True, all parent directories will be created if they don't exist.
        """
        path = pathlib.PurePath(path)
        current_pointer = self._project_files()
        for i, part in enumerate(path.parts):
            for child in current_pointer.children:
                if child.name == part:
                    if child.type != "folder":
                        raise FileExistsError("Cannot create directory: " + str(path))
                    current_pointer = child
                    if i == len(path.parts) - 1:
                        if not exist_ok:
                            raise FileExistsError("Cannot create directory: " + str(path))
                    break
            else:
                if i < len(path.parts) - 1 and not parents:
                    raise FileNotFoundError("No such file or directory: " + str(path))
                current_pointer = self._api.project_create_folder(self._project_id, current_pointer.id, part)

    def listdir(self, path: Union[pathlib.PurePath, str]) -> List[str]:
        """
        List the contents of a directory in the project.

        :param path: The path to the directory.
        :return: A list of the contents of the directory.
        """
        directory = self._find(path)
        if directory is None:
            raise FileNotFoundError("No such file or directory: " + str(path))
        return [child.name for child in directory.children]

    def remove(self, path: Union[pathlib.PurePath, str], missing_ok: bool = False) -> None:
        """
        Remove a file/directory from the project.

        :param path: The path to the file.
        """
        entity = self._find(path)
        if entity is None:
            if missing_ok:
                return
            raise FileNotFoundError("No such file or directory: " + str(path))
        self._api.project_delete_entity(self._project_id, entity)