import aioboto3
import os
from uuid import uuid4
from botocore.exceptions import ClientError
import logging
import aiohttp  # ← ДОБАВЬТЕ ЭТОТ ИМПОРТ

logger = logging.getLogger(__name__)


class SelectelS3Service:
    def __init__(self):
        self.bucket_name = os.getenv('S3_BUCKET_NAME', 'bike-rent-bucket')
        self.region = os.getenv('AWS_REGION', 'ru-7')
        self.endpoint_url = os.getenv('S3_ENDPOINT_URL', 'https://s3.ru-7.storage.selcloud.ru')  # ← ДЛЯ API
        self.access_domain = os.getenv('S3_ACCESS_DOMAIN',
                                       '8d92c38e-aea4-40e9-a271-ca9ce46f0cd0.selstorage.ru')  # ← ДЛЯ ДОСТУПА
        self.session = None
        self._initialize_session()

    def _initialize_session(self):
        """Инициализация асинхронной сессии"""
        try:
            self.session = aioboto3.Session(
                aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
                region_name=self.region
            )
            logger.info(f"Initialized async Selectel session: {self.endpoint_url}")
            logger.info(f"File access domain: {self.access_domain}")
        except Exception as e:
            logger.warning(f"Selectel session initialization warning: {e}")
            logger.warning("S3 service will use placeholder URLs")

    async def _ensure_bucket_exists(self):
        """Асинхронно проверяет и создает бакет если нужно"""
        if not self.session:
            return False

        try:
            async with self.session.client('s3', endpoint_url=self.endpoint_url, verify=False) as s3_client:
                await s3_client.head_bucket(Bucket=self.bucket_name)
                logger.info(f"Bucket {self.bucket_name} is accessible")
                return True
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                logger.info(f"Bucket {self.bucket_name} not found, creating...")
                try:
                    async with self.session.client('s3', endpoint_url=self.endpoint_url, verify=False) as s3_client:
                        await s3_client.create_bucket(
                            Bucket=self.bucket_name,
                            CreateBucketConfiguration={
                                'LocationConstraint': self.region
                            }
                        )
                    logger.info(f"Bucket {self.bucket_name} created successfully")
                    return True
                except Exception as create_error:
                    logger.error(f"Failed to create bucket: {create_error}")
                    return False
            else:
                logger.warning(f"Bucket access error: {error_code}")
                return False
        except Exception as e:
            logger.warning(f"Bucket check failed: {e}")
            return False

    def _get_file_url(self, file_key: str) -> str:
        """Формирует правильный URL для доступа к файлам"""
        # ✅ ИСПОЛЬЗУЕМ ДОМЕН ДЛЯ ДОСТУПА, А НЕ API ENDPOINT
        return f"https://{self.access_domain}/{file_key}"

    async def upload_file(self, file, filename: str) -> str:
        """Асинхронно загружает файл в Selectel Object Storage"""
        try:
            # ✅ АСИНХРОННО ПРОВЕРЯЕМ ДОСТУПНОСТЬ S3 ПЕРЕД ЗАГРУЗКОЙ
            if not self.session or not await self._ensure_bucket_exists():
                # ✅ ВОЗВРАЩАЕМ КРАСИВУЮ ЗАГЛУШКУ
                placeholder_url = "https://images.unsplash.com/photo-1485965120184-e220f721d03e?ixlib=rb-4.0.3&auto=format&fit=crop&w=500&q=80"
                logger.warning(f"S3 not available, using placeholder")
                return placeholder_url

            file_extension = filename.split('.')[-1].lower()
            unique_filename = f"{uuid4()}.{file_extension}"

            # ✅ ИСПОЛЬЗУЕМ API ENDPOINT ДЛЯ ЗАГРУЗКИ
            async with self.session.client('s3', endpoint_url=self.endpoint_url, verify=False) as s3_client:
                if hasattr(file, 'seek'):
                    file.seek(0)

                await s3_client.upload_fileobj(
                    file,
                    self.bucket_name,
                    unique_filename,
                    ExtraArgs={
                        'ACL': 'public-read',
                        'ContentType': self._get_content_type(file_extension)
                    }
                )

            # ✅ ИСПОЛЬЗУЕМ ДОМЕН ДЛЯ ДОСТУПА ДЛЯ URL
            file_url = self._get_file_url(unique_filename)
            logger.info(f"File uploaded successfully: {file_url}")

            # ✅ ПРОВЕРЯЕМ ДОСТУПНОСТЬ ФАЙЛА
            await self._verify_file_access(file_url)

            return file_url

        except Exception as e:
            logger.error(f"Selectel upload error: {e}")
            # ✅ ВОЗВРАЩАЕМ КРАСИВУЮ ЗАГЛУШКУ
            placeholder_url = "https://images.unsplash.com/photo-1485965120184-e220f721d03e?ixlib=rb-4.0.3&auto=format&fit=crop&w=500&q=80"
            logger.warning(f"Upload failed, using placeholder")
            return placeholder_url

    async def _verify_file_access(self, file_url: str):
        """Проверяет доступность файла по URL"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(file_url, timeout=10) as response:
                    if response.status == 200:
                        logger.info(f"✅ File is accessible: {file_url}")
                    else:
                        logger.warning(f"⚠️ File access issue: {file_url} - HTTP {response.status}")
        except Exception as e:
            logger.warning(f"⚠️ Could not verify file access: {file_url} - {e}")

    def _get_content_type(self, file_extension: str) -> str:
        """Определяет Content-Type по расширению файла"""
        content_types = {
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'gif': 'image/gif',
            'webp': 'image/webp',
            'svg': 'image/svg+xml',
            'bmp': 'image/bmp',
        }
        return content_types.get(file_extension.lower(), 'application/octet-stream')

    async def delete_file(self, file_url: str):
        """Асинхронно удаляет файл из Selectel"""
        if not self.session:
            logger.warning("S3 session not available, skip deletion")
            return

        try:
            file_key = file_url.split('/')[-1]
            # ✅ ИСПОЛЬЗУЕМ API ENDPOINT ДЛЯ УДАЛЕНИЯ
            async with self.session.client('s3', endpoint_url=self.endpoint_url, verify=False) as s3_client:
                await s3_client.delete_object(
                    Bucket=self.bucket_name,
                    Key=file_key
                )
            logger.info(f"File deleted from Selectel: {file_key}")
        except Exception as e:
            logger.error(f"Selectel delete error: {e}")


# Создаем экземпляр сервиса
s3_service = SelectelS3Service()


# Асинхронные функции для обратной совместимости
async def upload_file(file, filename: str) -> str:
    return await s3_service.upload_file(file, filename)


async def delete_file(file_url):
    return await s3_service.delete_file(file_url)