from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from pydantic import BaseModel
import uuid
from datetime import datetime, timezone
import asyncio

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.user import User, UserRole
from app.models.upload import Upload, UploadOrigin
from app.services.ai_service import AIService
from app.services.storage_service import StorageService

router = APIRouter()


class UploadResponse(BaseModel):
    id: str
    filename: str
    file_type: str
    uploaded_at: str
    status: str


@router.post("/", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Upload a file for AI processing"""
    if current_user.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Only students can upload files")
    
    try:
        # Read file content
        file_content = await file.read()
        
        # Validate file
        storage_service = StorageService()
        validation = await storage_service.validate_file(file_content, file.filename)
        
        if not validation["valid"]:
            raise HTTPException(status_code=400, detail="Invalid file type")
        
        # Upload to storage
        file_info = await storage_service.upload_file(
            file_content=file_content,
            original_filename=file.filename,
            user_id=str(current_user.id),
            file_type="study_material"
        )
        
        # Create upload record
        upload = Upload(
            user_id=str(current_user.id),
            file_key=file_info["file_key"],
            mime=file_info["mime_type"],
            bytes=file_info["file_size"],
            origin=UploadOrigin.NOTES,
            processed=False
        )
        
        db.add(upload)
        await db.commit()
        await db.refresh(upload)
        
        # Process file with AI (async)
        ai_service = AIService()
        asyncio.create_task(
            ai_service.process_document_upload(upload, str(current_user.id), db)
        )
        
        return UploadResponse(
            id=str(upload.id),
            filename=file.filename,
            file_type=file_info["mime_type"],
            uploaded_at=upload.created_at.isoformat(),
            status="processing"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.get("/", response_model=List[UploadResponse])
async def get_uploads(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's uploaded files"""
    if current_user.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Only students can view uploads")
    
    try:
        result = await db.execute(
            select(Upload).where(Upload.user_id == str(current_user.id))
        )
        uploads = result.scalars().all()
        
        return [
            UploadResponse(
                id=str(upload.id),
                filename=upload.file_key.split("/")[-1],  # Extract filename from key
                file_type=upload.mime,
                uploaded_at=upload.created_at.isoformat(),
                status="processed" if upload.processed else "processing"
            )
            for upload in uploads
        ]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch uploads: {str(e)}")


@router.delete("/{upload_id}")
async def delete_upload(
    upload_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete an uploaded file"""
    if current_user.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Only students can delete uploads")
    
    try:
        result = await db.execute(
            select(Upload).where(
                and_(
                    Upload.id == upload_id,
                    Upload.user_id == str(current_user.id)
                )
            )
        )
        upload = result.scalar_one_or_none()
        
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")
        
        # Delete from storage
        storage_service = StorageService()
        await storage_service.delete_file(upload.file_key)
        
        # Delete embeddings
        ai_service = AIService()
        await ai_service.delete_document_embeddings(str(upload.id), str(current_user.id))
        
        # Delete from database
        await db.delete(upload)
        await db.commit()
        
        return {"message": "Upload deleted successfully"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete upload: {str(e)}")
