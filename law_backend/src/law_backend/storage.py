from qcloud_cos import CosConfig, CosS3Client

from .config import settings


def client(config):
    if not all(config.get(k) for k in ("region", "bucket", "secret_id", "secret_key")):
        raise ValueError("请完整配置 COS 地域、存储桶和密钥")
    return CosS3Client(
        CosConfig(
            Region=config["region"],
            SecretId=config["secret_id"],
            SecretKey=config["secret_key"],
            Scheme="https",
            Timeout=30,
        )
    )


def location(config):
    # Credentials are never persisted on material records.
    return {k: config.get(k, "") for k in ("mode", "region", "bucket")}


def local_path(key):
    root = settings.data_dir.resolve()
    dest = (root / key).resolve()
    if not dest.is_relative_to(root):
        raise ValueError("无效对象路径")
    return dest


def put(key, data: bytes, config, mime="application/octet-stream"):
    if config["mode"] == "cos":
        client(config).put_object(Bucket=config["bucket"], Key=key, Body=data, ContentType=mime)
    else:
        dest = local_path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)


def get(key, loc, config):
    if loc["mode"] == "cos":
        current = {**config, "region": loc["region"], "bucket": loc["bucket"]}
        response = client(current).get_object(Bucket=loc["bucket"], Key=key)
        stream = response["Body"].get_raw_stream()
        try:
            return stream.read()
        finally:
            stream.close()
    return local_path(key).read_bytes()


def test_cos(config):
    client(config).head_bucket(Bucket=config["bucket"])
    return {"ok": True, "message": "COS 存储桶可访问；上传权限在实际上传时验证。"}
