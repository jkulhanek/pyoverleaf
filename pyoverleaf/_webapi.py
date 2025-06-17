from base64 import b64encode
import ssl
import urllib.parse
import time
try:
    import http.cookiejar as cookielib
except ImportError:
    import cookielib  # type: ignore
from typing import List, Optional, Union, overload, Literal, Dict
import json
from dataclasses import dataclass, field
from websocket import create_connection
import browsercookie
import requests
from bs4 import BeautifulSoup


@dataclass
class User:
    id: str
    email: str
    first_name: str
    last_name: str

    @classmethod
    def from_data(cls, data: dict):
        return cls(
            id=data["id"],
            email=data["email"],
            first_name=data["firstName"],
            last_name=data["lastName"],
        )


@dataclass
class Tag:
    id: str
    name: str
    color: str

    @classmethod
    def from_data(cls, data: dict):
        return cls(
            id=data["_id"],
            name=data["name"],
            color=data["color"],
        )


@dataclass
class Project:
    id: str
    name: str
    last_updated: str
    access_level: str
    source: str
    archived: bool
    trashed: bool
    owner: Optional[User] = None
    last_updated_by: Optional[User] = None
    tags: Optional[List[Tag]] = field(default_factory=list)

    @classmethod
    def from_data(cls, data: dict):
        out = cls(
            id=data["id"],
            name=data["name"],
            last_updated=data["lastUpdated"],
            access_level=data["accessLevel"],
            source=data["source"],
            archived=data["archived"],
            trashed=data["trashed"],
        )

        owner_data = data.get("owner")
        if owner_data is not None:
            out.owner = User.from_data(owner_data)

        last_updated_by_data = data.get("lastUpdatedBy")
        if last_updated_by_data is not None:
            out.last_updated_by = User.from_data(last_updated_by_data)

        return out


@dataclass
class ProjectFile:
    id: str
    name: str
    created: Optional[str]
    type: Literal["file", "doc"] = "file"

    @classmethod
    def from_data(cls, data: dict):
        return cls(
            id=data["_id"],
            name=data["name"],
            created=data.get("created", None),
        )

    def __str__(self):
        return self.name

@dataclass
class ProjectFolder:
    id: str
    name: str
    children: List[Union[ProjectFile, "ProjectFolder"]] = field(default_factory=list)

    @classmethod
    def from_data(cls, data: dict):
        out = cls(
            id=data["_id"],
            name=data["name"],
        )
        for child in data["folders"]:
            out.children.append(ProjectFolder.from_data(child))

        for child in data["fileRefs"]:
            out.children.append(ProjectFile.from_data(child))

        for child in data["docs"]:
            doc = ProjectFile.from_data(child)
            doc.type = "doc"
            out.children.append(doc)
        return out

    def __str__(self):
        out = self.name + ":"
        for child in self.children:
            child_str = str(child)
            out += "\n"
            for line in child_str.splitlines(True):
                out += "  " + line
        return out

    @property
    def type(self):
        return "folder"



class Api:
    def __init__(self, *, timeout: int = 16, proxies=None, ssl_verify: bool = True):
        self._session_initialized = False
        self._cookies = None
        self._request_kwargs = { "timeout": timeout }
        self._proxies = proxies
        self._ssl_verify = ssl_verify
        self._csrf_cache = None

    def get_projects(self, *, trashed: bool = False, archived: bool = False) -> List[Project]:
        """
        Get the full list of projects.

        :param trashed: Whether to include trashed projects.
        :param archived: Whether to include archived projects.
        :return: A list of projects.
        """
        self._assert_session_initialized()
        r = self._get_session().get("https://overleaf.com/", **self._request_kwargs)
        r.raise_for_status()
        content = BeautifulSoup(r.content, features="html.parser")
        data = content.find("meta", dict(name="ol-prefetchedProjectsBlob")).get("content")
        data = json.loads(data)
        projects = []
        for project_data in data["projects"]:
            proj = Project.from_data(project_data)
            if not trashed and proj.trashed:
                continue
            if not archived and proj.archived:
                continue
            projects.append(proj)

        # Add tags to projects
        tags = content.find("meta", dict(name="ol-tags")).get("content")
        tags = json.loads(tags)
        proj_map = {proj.id: proj for proj in projects}
        for tag_data in tags:
            tag = Tag.from_data(tag_data)
            for project_id in tag_data["project_ids"]:
                if project_id in proj_map:
                    project = proj_map[project_id]
                    if not hasattr(project, "tags"):
                        project.tags = []
                    project.tags.append(tag)
        return projects

    @overload
    def download_project(self, project_id: str) -> bytes:
        ...

    @overload
    def download_project(self, project_id: str, output_path: str) -> None:
        ...

    def download_project(self, project_id: str, output_path: Optional[str] = None) -> Union[bytes, None]:
        """
        Download a project as a zip file.

        :param project_id: The id of the project to download.
        :param output_path: The path to save the project to. If none, the project will be returned as bytes.
        :return: The zipped project if output_path is None, else None.
        """
        self._assert_session_initialized()
        r = self._get_session().get(f"https://www.overleaf.com/project/{project_id}/download/zip", **self._request_kwargs)
        r.raise_for_status()
        if output_path is not None:
            with open(output_path, "wb") as f:
                f.write(r.content)
            return None
        return r.content

    def project_get_files(self, project_id: str) -> ProjectFolder:
        """
        Get the root directory of a project.

        :param project_id: The id of the project.
        :return: The root directory of the project.
        """
        data = None
        socket = self._open_socket(project_id)
        while True:
            line = socket.recv()
            if line.startswith("7:"):
                # Unauthorized. TODO: handle this.
                raise RuntimeError("Could not get project files.")
            if line.startswith("5:"):
                break
        data = json.loads(line[len("5:"):].lstrip(":"))

        # Parse the data
        assert data["name"] == "joinProjectResponse"
        data = data["args"][0]
        assert len(data["project"]["rootFolder"]) == 1
        return ProjectFolder.from_data(data["project"]["rootFolder"][0])

    def project_create_folder(self, project_id: str, parent_folder_id: str, folder_name: str) -> ProjectFolder:
        """
        Create a folder in a project.

        :param project_id: The id of the project.
        :param parent_folder_id: The id of the parent folder.
        :param folder_name: The name of the folder.
        """
        self._assert_session_initialized()
        r = self._get_session().post(f"https://www.overleaf.com/project/{project_id}/folder", json={
            "parent_folder_id": parent_folder_id,
            "name": folder_name
        }, **self._request_kwargs, headers={
            "Referer": f"https://www.overleaf.com/project/{project_id}",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "x-csrf-token": self._get_csrf_token(project_id),
        })
        r.raise_for_status()
        new_project_folder = ProjectFolder.from_data(json.loads(r.content))
        return new_project_folder

    def project_upload_file(self, project_id: str, folder_id: str, file_name: str, file_content: bytes) -> ProjectFile:
        """
        Upload a file to a project.

        :param project_id: The id of the project.
        :param folder_id: The id of the folder to upload to.
        :param file_name: The name of the file.
        :param file_content: The content of the file.
        """
        mime = "application/octet-stream"
        self._assert_session_initialized()
        r = self._get_session().post(f"https://www.overleaf.com/project/{project_id}/upload?folder_id={folder_id}",
            files={
                "relativePath": (None, "null"),
                "name": (None, file_name),
                "type": (None, mime),
                "qqfile": (file_name, file_content, mime),
            }, **self._request_kwargs, headers={
            "Referer": f"https://www.overleaf.com/project/{project_id}",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "x-csrf-token": self._get_csrf_token(project_id),
        })
        r.raise_for_status()
        response = json.loads(r.content)
        new_file = ProjectFile(
            response["entity_id"],
            name=file_name,
            created=None,
            type=response["entity_type"])
        return new_file

    @overload
    def project_download_file(self, project_id: str, file: ProjectFile) -> bytes:
        ...

    @overload
    def project_download_file(self, project_id: str, file: ProjectFile, output_path: str) -> None:
        ...

    def project_download_file(self, project_id: str, file: ProjectFile, output_path: Optional[str] = None) -> Union[bytes, None]:
        """
        Download a file from a project.
        
        :param project_id: The id of the project.
        :param file: The file to download.
        :param output_path: The path to save the file to. If none, the file will be returned as bytes.
        :return: The file if output_path is None, else None.
        """
        self._assert_session_initialized()
        if file.type == "file":
            r = self._get_session().get(f"https://www.overleaf.com/project/{project_id}/file/{file.id}", **self._request_kwargs)  # pylint: disable=protected-access
            r.raise_for_status()
            if output_path is not None:
                with open(output_path, "wb") as f:
                    f.write(r.content)
                return None
            return r.content
        elif file.type == "doc":
            return self._pull_doc_project_file_content(project_id, file.id).encode("utf-8")
        else:
            raise ValueError(f"Unknown file type: {file.type}")

    @overload
    def project_delete_entity(self, project_id: str, entity: Union[ProjectFile, ProjectFolder]) -> None:
        ...

    @overload
    def project_delete_entity(self, project_id: str, entity: str, entity_type: Literal["file", "doc", "folder"]) -> None:
        ...

    def project_delete_entity(self, project_id: str, entity, entity_type=None) -> None:
        """
        Delete a file/folder/doc from the project

        :param project_id: The id of the project.
        :param entity_id: The id of the entity to delete.
        """
        if entity_type is None:
            assert isinstance(entity, ProjectFile) or isinstance(entity, ProjectFolder)
            entity_type = entity.type
            entity = entity.id
        else:
            assert isinstance(entity, str)
        self._assert_session_initialized()
        r = self._get_session().delete(f"https://www.overleaf.com/project/{project_id}/{entity_type}/{entity}", json={}, **self._request_kwargs, headers={
            "Referer": f"https://www.overleaf.com/project/{project_id}",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "x-csrf-token": self._get_csrf_token(project_id),
        })
        r.raise_for_status()

    def login_from_browser(self):
        """
        Login to Overleaf using the default browser's cookies.
        """
        cookies = browsercookie.load()
        self.login_from_cookies(cookies)

    @overload
    def login_from_cookies(self, cookies: Dict[str, str]):
        """
        Login to Overleaf using a dictionary of cookies.
        """

    @overload
    def login_from_cookies(self, cookies: cookielib.CookieJar):
        """
        Login to Overleaf using a CookieJar.
        """

    def login_from_cookies(self, cookies):
        if not isinstance(cookies, cookielib.CookieJar):
            assert isinstance(cookies, dict)
            cookies_jar = cookielib.CookieJar()
            for name, value in cookies.items():
                cookies_jar.set_cookie(requests.cookies.create_cookie(name, value, domain=".overleaf.com"))
            cookies = cookies_jar

        assert isinstance(cookies, cookielib.CookieJar)
        self._cookies = cookielib.CookieJar()
        for cookie in cookies:
            if cookie.domain.endswith(".overleaf.com"):
                self._cookies.set_cookie(cookie)
        self._session_initialized = True

    def _pull_doc_project_file_content(self, project_id: str, file_id: str) -> str:
        socket = None
        try:
            socket = self._open_socket(project_id)

            # Initial waiting
            while True:
                line = socket.recv()
                if line.startswith("7:"):
                    # Unauthorized. TODO: handle this.
                    raise RuntimeError("Could not get project files.")
                if line.startswith("5:"):
                    break
            socket.send('5:1+::{"name":"clientTracking.getConnectedUsers"}'.encode("utf-8"))

            # Join the doc
            socket.send(f'5:2+::{{"name": "joinDoc", "args": ["{file_id}", {{"encodeRanges": true}}]}}'.encode("utf-8"))
            while True:
                line = socket.recv()
                if line.startswith("7:"):
                    # Unauthorized. TODO: handle this.
                    raise RuntimeError("Could not get project files.")
                if line.startswith("6:::2+"):
                    break
            data = line[6:]

            # Leave doc
            socket.send(f"5:3+::{{\"name\": \"leaveDoc\", \"args\": [\"{file_id}\"]}}".encode("utf-8"))
            while True:
                line = socket.recv()
                if line.startswith("7:"):
                    # Unauthorized. TODO: handle this.
                    raise RuntimeError("Could not get project files.")
                if line.startswith("6:::3+"):
                    break
        finally:
            if socket is not None:
                socket.close()
                socket = None
        return "\n".join(json.loads(data)[1])

    def _get_session(self):
        self._assert_session_initialized()
        http_session = requests.Session()
        http_session.cookies = self._cookies
        http_session.proxies = self._proxies
        http_session.verify = self._ssl_verify
        return http_session

    def _assert_session_initialized(self):
        if not self._session_initialized:
            raise RuntimeError("Must call api.login_*() before using the api")

    def _get_csrf_token(self, project_id):
        self._assert_session_initialized()
        # First we pull the csrf token
        if self._csrf_cache is not None and self._csrf_cache[0] == project_id:
            return self._csrf_cache[1]
        r = self._get_session().get(f"https://www.overleaf.com/project/{project_id}", **self._request_kwargs)
        r.raise_for_status()
        content = BeautifulSoup(r.content, features="html.parser")
        token = content.find("meta", dict(name="ol-csrfToken")).get("content")
        self._csrf_cache = (project_id, token)
        return token

    def _open_socket(self, project_id: str) -> bytes:
        self._assert_session_initialized()
        time_now = int(time.time() * 1000)
        session = self._get_session()  # pylint: disable=protected-access
        r = session.get(
            f"https://www.overleaf.com/socket.io/1/?projectId={project_id}&t={time_now}", **self._request_kwargs)  # pylint: disable=protected-access
        r.raise_for_status()
        content = r.content.decode("utf-8")
        socket_id = content.split(":")[0]
        socket_url = f"wss://www.overleaf.com/socket.io/1/websocket/{socket_id}?projectId={project_id}"
        kwargs = {}
        cookies = None

        cookies = "; ".join([f"{c.name}={c.value}" for c in session.cookies if c.domain.endswith(".overleaf.com")])
        headers = dict(**session.headers)
        for header, value in headers.items():
            if header.lower() == 'cookie':
                if cookies:
                    cookies += '; '
                cookies += value
                del headers[header]
                break

        # auth
        if 'Authorization' not in headers and session.auth is not None:
            if not isinstance(session.auth, tuple):  # pragma: no cover
                raise ValueError('Only basic authentication is supported')
            basic_auth = f'{session.auth[0]}:{session.auth[1]}'.encode('utf-8')  # pylint: disable=unsubscriptable-object
            basic_auth = b64encode(basic_auth).decode('utf-8')
            headers['Authorization'] = 'Basic ' + basic_auth

        # cert
        # this can be given as ('certfile', 'keyfile') or just 'certfile'
        if isinstance(session.cert, tuple):
            kwargs['sslopt'] = {
                'certfile': session.cert[0],  # pylint: disable=unsubscriptable-object
                'keyfile': session.cert[1]}  # pylint: disable=unsubscriptable-object
        elif session.cert:
            kwargs['sslopt'] = {'certfile': session.cert}

        # proxies
        if session.proxies:
            proxy_url = None
            if socket_url.startswith('ws://'):
                proxy_url = session.proxies.get(
                    'ws', session.proxies.get('http'))
            else:  # wss://
                proxy_url = session.proxies.get(
                    'wss', session.proxies.get('https'))
            if proxy_url:
                parsed_url = urllib.parse.urlparse(
                    proxy_url if '://' in proxy_url
                    else 'scheme://' + proxy_url)
                kwargs['http_proxy_host'] = parsed_url.hostname
                kwargs['http_proxy_port'] = parsed_url.port
                kwargs['http_proxy_auth'] = (
                    (parsed_url.username, parsed_url.password)
                    if parsed_url.username or parsed_url.password
                    else None)

        # verify
        if isinstance(session.verify, str):
            if 'sslopt' in kwargs:
                kwargs['sslopt']['ca_certs'] = session.verify
            else:
                kwargs['sslopt'] = {'ca_certs': session.verify}
        elif not session.verify:
            kwargs['sslopt'] = {"cert_reqs": ssl.CERT_NONE}

        # combine internally generated options with the ones supplied by the
        # caller. The caller's options take precedence.
        kwargs['header'] = headers
        kwargs['cookie'] = cookies
        kwargs['enable_multithread'] = True
        if 'timeout' in self._request_kwargs:
            kwargs['timeout'] = self._request_kwargs['timeout']
        return create_connection(socket_url, **kwargs)
