import boto3
import asyncio
import logging
from typing import Optional, Dict, Any
from pathlib import Path
import uuid
import mimetypes
from datetime import datetime, timezone
import aiofiles
import tempfile
import os

from app.core.config import settings
from app.core.exceptions import FileUploadError

logger = logging.getLogger(__name__)


class StorageService:
    """Storage service for file uploads to S3 or Supabase Storage"""
    
    def __init__(self):
        self.storage_type = settings.STORAGE_TYPE  # "s3" or "supabase"
        
        if self.storage_type == "s3":
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION
            )
            self.bucket_name = settings.AWS_S3_BUCKET
        elif self.storage_type == "supabase":
            # Initialize Supabase client
            import supabase
            self.supabase_client = supabase.create_client(
                settings.SUPABASE_URL,
                settings.SUPABASE_ANON_KEY
            )
            self.bucket_name = settings.SUPABASE_STORAGE_BUCKET
    
    async def upload_file(
        self,
        file_content: bytes,
        original_filename: str,
        user_id: str,
        file_type: str = "notes"
    ) -> Dict[str, Any]:
        """Upload file to storage and return file information"""
        try:
            # Generate unique file key
            file_extension = Path(original_filename).suffix
            file_key = f"{user_id}/{file_type}/{uuid.uuid4()}{file_extension}"
            
            # Determine MIME type
            mime_type, _ = mimetypes.guess_type(original_filename)
            if not mime_type:
                mime_type = "application/octet-stream"
            
            # Upload based on storage type
            if self.storage_type == "s3":
                await self._upload_to_s3(file_content, file_key, mime_type)
            elif self.storage_type == "supabase":
                await self._upload_to_supabase(file_content, file_key, mime_type)
            else:
                raise FileUploadError(f"Unsupported storage type: {self.storage_type}")
            
            # Return file information
            return {
                "file_key": file_key,
                "original_filename": original_filename,
                "mime_type": mime_type,
                "file_size": len(file_content),
                "uploaded_at": datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error uploading file {original_filename}: {e}")
            raise FileUploadError(f"Failed to upload file: {str(e)}")
    
    async def download_file(self, file_key: str) -> bytes:
        """Download file from storage"""
        try:
            if self.storage_type == "s3":
                return await self._download_from_s3(file_key)
            elif self.storage_type == "supabase":
                return await self._download_from_supabase(file_key)
            else:
                raise FileUploadError(f"Unsupported storage type: {self.storage_type}")
                
        except Exception as e:
            logger.error(f"Error downloading file {file_key}: {e}")
            raise FileUploadError(f"Failed to download file: {str(e)}")
    
    async def delete_file(self, file_key: str) -> bool:
        """Delete file from storage"""
        try:
            if self.storage_type == "s3":
                return await self._delete_from_s3(file_key)
            elif self.storage_type == "supabase":
                return await self._delete_from_supabase(file_key)
            else:
                raise FileUploadError(f"Unsupported storage type: {self.storage_type}")
                
        except Exception as e:
            logger.error(f"Error deleting file {file_key}: {e}")
            raise FileUploadError(f"Failed to delete file: {str(e)}")
    
    async def get_file_url(self, file_key: str, expires_in: int = 3600) -> str:
        """Get presigned URL for file access"""
        try:
            if self.storage_type == "s3":
                return await self._get_s3_presigned_url(file_key, expires_in)
            elif self.storage_type == "supabase":
                return await self._get_supabase_url(file_key)
            else:
                raise FileUploadError(f"Unsupported storage type: {self.storage_type}")
                
        except Exception as e:
            logger.error(f"Error getting file URL for {file_key}: {e}")
            raise FileUploadError(f"Failed to get file URL: {str(e)}")
    
    async def _upload_to_s3(self, file_content: bytes, file_key: str, mime_type: str):
        """Upload file to S3"""
        try:
            # Use asyncio to run S3 upload in thread pool
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key=file_key,
                    Body=file_content,
                    ContentType=mime_type,
                    Metadata={
                        'uploaded_at': datetime.now(timezone.utc).isoformat()
                    }
                )
            )
            
            logger.info(f"Successfully uploaded {file_key} to S3")
            
        except Exception as e:
            logger.error(f"Error uploading to S3: {e}")
            raise FileUploadError(f"S3 upload failed: {str(e)}")
    
    async def _download_from_s3(self, file_key: str) -> bytes:
        """Download file from S3"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.s3_client.get_object(
                    Bucket=self.bucket_name,
                    Key=file_key
                )
            )
            
            file_content = response['Body'].read()
            logger.info(f"Successfully downloaded {file_key} from S3")
            return file_content
            
        except Exception as e:
            logger.error(f"Error downloading from S3: {e}")
            raise FileUploadError(f"S3 download failed: {str(e)}")
    
    async def _delete_from_s3(self, file_key: str) -> bool:
        """Delete file from S3"""
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.s3_client.delete_object(
                    Bucket=self.bucket_name,
                    Key=file_key
                )
            )
            
            logger.info(f"Successfully deleted {file_key} from S3")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting from S3: {e}")
            raise FileUploadError(f"S3 delete failed: {str(e)}")
    
    async def _get_s3_presigned_url(self, file_key: str, expires_in: int) -> str:
        """Get presigned URL for S3 file"""
        try:
            loop = asyncio.get_event_loop()
            url = await loop.run_in_executor(
                None,
                lambda: self.s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': self.bucket_name, 'Key': file_key},
                    ExpiresIn=expires_in
                )
            )
            
            return url
            
        except Exception as e:
            logger.error(f"Error generating S3 presigned URL: {e}")
            raise FileUploadError(f"S3 presigned URL generation failed: {str(e)}")
    
    async def _upload_to_supabase(self, file_content: bytes, file_key: str, mime_type: str):
        """Upload file to Supabase Storage"""
        try:
            # Create temporary file
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                temp_file.write(file_content)
                temp_file_path = temp_file.name
            
            try:
                # Upload to Supabase
                response = self.supabase_client.storage.from_(self.bucket_name).upload(
                    path=file_key,
                    file=temp_file_path,
                    file_options={
                        "content-type": mime_type
                    }
                )
                
                logger.info(f"Successfully uploaded {file_key} to Supabase")
                
            finally:
                # Clean up temporary file
                os.unlink(temp_file_path)
                
        except Exception as e:
            logger.error(f"Error uploading to Supabase: {e}")
            raise FileUploadError(f"Supabase upload failed: {str(e)}")
    
    async def _download_from_supabase(self, file_key: str) -> bytes:
        """Download file from Supabase Storage"""
        try:
            # Download from Supabase
            response = self.supabase_client.storage.from_(self.bucket_name).download(file_key)
            
            logger.info(f"Successfully downloaded {file_key} from Supabase")
            return response
            
        except Exception as e:
            logger.error(f"Error downloading from Supabase: {e}")
            raise FileUploadError(f"Supabase download failed: {str(e)}")
    
    async def _delete_from_supabase(self, file_key: str) -> bool:
        """Delete file from Supabase Storage"""
        try:
            # Delete from Supabase
            response = self.supabase_client.storage.from_(self.bucket_name).remove([file_key])
            
            logger.info(f"Successfully deleted {file_key} from Supabase")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting from Supabase: {e}")
            raise FileUploadError(f"Supabase delete failed: {str(e)}")
    
    async def _get_supabase_url(self, file_key: str) -> str:
        """Get public URL for Supabase file"""
        try:
            # Get public URL from Supabase
            response = self.supabase_client.storage.from_(self.bucket_name).get_public_url(file_key)
            
            return response
            
        except Exception as e:
            logger.error(f"Error getting Supabase URL: {e}")
            raise FileUploadError(f"Supabase URL generation failed: {str(e)}")
    
    async def validate_file(
        self,
        file_content: bytes,
        original_filename: str,
        max_size_mb: int = 50
    ) -> Dict[str, Any]:
        """Validate uploaded file"""
        try:
            # Check file size
            file_size_mb = len(file_content) / (1024 * 1024)
            if file_size_mb > max_size_mb:
                raise FileUploadError(f"File size {file_size_mb:.2f}MB exceeds maximum allowed size of {max_size_mb}MB")
            
            # Check file extension
            allowed_extensions = {
                '.pdf', '.docx', '.doc', '.pptx', '.ppt', 
                '.txt', '.md', '.rtf', '.odt', '.ods', '.odp'
            }
            
            file_extension = Path(original_filename).suffix.lower()
            if file_extension not in allowed_extensions:
                raise FileUploadError(f"File type {file_extension} is not supported")
            
            # Check MIME type
            mime_type, _ = mimetypes.guess_type(original_filename)
            allowed_mime_types = {
                'application/pdf',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'application/msword',
                'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                'application/vnd.ms-powerpoint',
                'text/plain',
                'text/markdown',
                'application/rtf',
                'application/vnd.oasis.opendocument.text',
                'application/vnd.oasis.opendocument.spreadsheet',
                'application/vnd.oasis.opendocument.presentation'
            }
            
            if mime_type and mime_type not in allowed_mime_types:
                raise FileUploadError(f"MIME type {mime_type} is not supported")
            
            return {
                "valid": True,
                "file_size_mb": file_size_mb,
                "file_extension": file_extension,
                "mime_type": mime_type
            }
            
        except FileUploadError:
            raise
        except Exception as e:
            logger.error(f"Error validating file {original_filename}: {e}")
            raise FileUploadError(f"File validation failed: {str(e)}")
    
    async def get_storage_usage(self, user_id: str) -> Dict[str, Any]:
        """Get storage usage statistics for user"""
        try:
            if self.storage_type == "s3":
                return await self._get_s3_usage(user_id)
            elif self.storage_type == "supabase":
                return await self._get_supabase_usage(user_id)
            else:
                return {"total_files": 0, "total_size_mb": 0}
                
        except Exception as e:
            logger.error(f"Error getting storage usage for user {user_id}: {e}")
            return {"total_files": 0, "total_size_mb": 0}
    
    async def _get_s3_usage(self, user_id: str) -> Dict[str, Any]:
        """Get S3 storage usage for user"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.s3_client.list_objects_v2(
                    Bucket=self.bucket_name,
                    Prefix=f"{user_id}/"
                )
            )
            
            total_files = 0
            total_size_bytes = 0
            
            if 'Contents' in response:
                for obj in response['Contents']:
                    total_files += 1
                    total_size_bytes += obj['Size']
            
            return {
                "total_files": total_files,
                "total_size_mb": total_size_bytes / (1024 * 1024)
            }
            
        except Exception as e:
            logger.error(f"Error getting S3 usage: {e}")
            return {"total_files": 0, "total_size_mb": 0}
    
    async def _get_supabase_usage(self, user_id: str) -> Dict[str, Any]:
        """Get Supabase storage usage for user"""
        try:
            # List files in user's directory
            response = self.supabase_client.storage.from_(self.bucket_name).list(path=f"{user_id}/")
            
            total_files = 0
            total_size_bytes = 0
            
            for file_info in response:
                total_files += 1
                total_size_bytes += file_info.get('metadata', {}).get('size', 0)
            
            return {
                "total_files": total_files,
                "total_size_mb": total_size_bytes / (1024 * 1024)
            }
            
        except Exception as e:
            logger.error(f"Error getting Supabase usage: {e}")
            return {"total_files": 0, "total_size_mb": 0}
