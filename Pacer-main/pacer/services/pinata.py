import os
import requests

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


def _get_api_key():
    return os.environ.get("PINATA_API_KEY", "")


def _get_secret_key():
    return os.environ.get("PINATA_SECRET_KEY", "")


def _get_gateway_url():
    return os.environ.get("PINATA_GATEWAY_URL", "https://gateway.pinata.cloud/ipfs/")


def pinata_configured():
    return bool(_get_api_key() and _get_secret_key())


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def upload_to_pinata(file_storage, filename=None):
    if not pinata_configured():
        return None
    if not filename:
        filename = file_storage.filename
    if not allowed_file(filename):
        return None
    file_storage.seek(0, 2)
    size = file_storage.tell()
    file_storage.seek(0)
    if size > MAX_FILE_SIZE:
        return None
    try:
        file_bytes = file_storage.read()
        content_type = file_storage.content_type or "application/octet-stream"
        resp = requests.post(
            "https://api.pinata.cloud/pinning/pinFileToIPFS",
            files={"file": (filename, file_bytes, content_type)},
            headers={
                "pinata_api_key": _get_api_key(),
                "pinata_secret_api_key": _get_secret_key(),
            },
        )
        if resp.status_code == 200:
            return resp.json().get("IpfsHash")
        return None
    except requests.RequestException:
        return None


def get_ipfs_url(cid):
    if not cid:
        return None
    return f"{_get_gateway_url()}{cid}"
