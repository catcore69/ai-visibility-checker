import asyncio
from typing import Optional

import boto3
from botocore.client import Config

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class S3Client:
    def __init__(self):
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION,
            config=Config(signature_version="s3v4"),
        )
        self.bucket = settings.S3_BUCKET

    async def upload_bytes(self, key: str, data: bytes, content_type: str = "application/pdf") -> str:
        """Загружает файл в S3, возвращает публичный URL."""
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        logger.info("s3_uploaded", key=key, size=len(data))
        return f"{settings.S3_ENDPOINT_URL}/{self.bucket}/{key}"

    async def generate_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Генерирует pre-signed URL для скачивания."""
        url = await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        return url

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(
            self._client.delete_object,
            Bucket=self.bucket,
            Key=key,
        )
