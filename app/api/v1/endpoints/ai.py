from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from pydantic import BaseModel, Field
import uuid
from datetime import datetime, timezone

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.user import User, UserRole
from app.models.upload import Upload, UploadOrigin
from app.models.ai_artifact import AIArtifact, AIArtifactType, AIArtifactStatus
from app.services.ai_service import AIService
from app.services.storage_service import StorageService
from app.core.exceptions import AIProcessingError, FileUploadError

router = APIRouter()


# Pydantic models for request/response
class UploadResponse(BaseModel):
    upload_id: str
    file_key: str
    original_filename: str
    mime_type: str
    file_size: int
    processed: bool


class QAResponse(BaseModel):
    answer: str
    sources: List[dict]
    confidence: float


class SummaryResponse(BaseModel):
    artifact_id: str
    summary: dict


class FlashcardResponse(BaseModel):
    artifact_id: str
    flashcards: List[dict]


class QuizResponse(BaseModel):
    artifact_id: str
    quiz: dict


class AIArtifactResponse(BaseModel):
    artifact_id: str
    type: str
    status: str
    payload: dict
    created_at: str


# File Upload Endpoints
@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    origin: UploadOrigin = Body(UploadOrigin.NOTES),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Upload document for AI processing"""
    if current_user.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Only students can upload documents")
    
    try:
        # Read file content
        file_content = await file.read()
        
        # Validate file
        storage_service = StorageService()
        validation = await storage_service.validate_file(file_content, file.filename)
        
        if not validation["valid"]:
            raise HTTPException(status_code=400, detail="Invalid file")
        
        # Upload to storage
        file_info = await storage_service.upload_file(
            file_content=file_content,
            original_filename=file.filename,
            user_id=str(current_user.id),
            file_type=origin.value
        )
        
        # Create upload record
        upload = Upload(
            user_id=str(current_user.id),
            file_key=file_info["file_key"],
            mime=file_info["mime_type"],
            bytes=file_info["file_size"],
            origin=origin,
            processed=False
        )
        
        db.add(upload)
        await db.commit()
        await db.refresh(upload)
        
        # Process document in background (in production, use Celery)
        ai_service = AIService()
        await ai_service.process_document_upload(upload, str(current_user.id), db)
        
        return UploadResponse(
            upload_id=str(upload.id),
            file_key=upload.file_key,
            original_filename=file.filename,
            mime_type=upload.mime,
            file_size=upload.bytes,
            processed=upload.processed
        )
        
    except FileUploadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/uploads", response_model=List[UploadResponse])
async def get_uploads(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's uploaded documents"""
    try:
        uploads = await db.execute(
            select(Upload).where(
                and_(
                    Upload.user_id == str(current_user.id),
                    Upload.deleted_at.is_(None)
                )
            ).order_by(Upload.created_at.desc())
        ).scalars().all()
        
        return [
            UploadResponse(
                upload_id=str(upload.id),
                file_key=upload.file_key,
                original_filename=upload.file_key.split("/")[-1],  # Extract filename from key
                mime_type=upload.mime,
                file_size=upload.bytes,
                processed=upload.processed
            )
            for upload in uploads
        ]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/uploads/{upload_id}")
async def delete_upload(
    upload_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete uploaded document"""
    try:
        upload = await db.execute(
            select(Upload).where(
                and_(
                    Upload.id == upload_id,
                    Upload.user_id == str(current_user.id),
                    Upload.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")
        
        # Delete from storage
        storage_service = StorageService()
        await storage_service.delete_file(upload.file_key)
        
        # Delete embeddings from Pinecone
        ai_service = AIService()
        await ai_service.delete_document_embeddings(str(current_user.id), upload_id)
        
        # Soft delete from database
        upload.deleted_at = datetime.now(timezone.utc)
        await db.commit()
        
        return {"message": "Upload deleted successfully"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


# AI Q&A Endpoints
@router.post("/qa", response_model=QAResponse)
async def semantic_qa(
    question: str = Body(..., embed=True),
    upload_id: Optional[str] = Body(None, embed=True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Ask semantic question about uploaded documents"""
    if current_user.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Only students can use AI Q&A")
    
    try:
        ai_service = AIService()
        result = await ai_service.semantic_qa(
            user_id=str(current_user.id),
            question=question,
            upload_id=upload_id,
            db_session=db
        )
        
        return QAResponse(
            answer=result["answer"],
            sources=result["sources"],
            confidence=result["confidence"]
        )
        
    except AIProcessingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


# Content Generation Endpoints
@router.post("/summary/{upload_id}", response_model=SummaryResponse)
async def generate_summary(
    upload_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Generate document summary"""
    if current_user.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Only students can generate summaries")
    
    try:
        # Verify upload belongs to user
        upload = await db.execute(
            select(Upload).where(
                and_(
                    Upload.id == upload_id,
                    Upload.user_id == str(current_user.id),
                    Upload.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")
        
        ai_service = AIService()
        result = await ai_service.generate_summary(
            user_id=str(current_user.id),
            upload_id=upload_id,
            db_session=db
        )
        
        return SummaryResponse(
            artifact_id=result["artifact_id"],
            summary=result["summary"]
        )
        
    except AIProcessingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/flashcards/{upload_id}", response_model=FlashcardResponse)
async def generate_flashcards(
    upload_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Generate flashcards from document"""
    if current_user.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Only students can generate flashcards")
    
    try:
        # Verify upload belongs to user
        upload = await db.execute(
            select(Upload).where(
                and_(
                    Upload.id == upload_id,
                    Upload.user_id == str(current_user.id),
                    Upload.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")
        
        ai_service = AIService()
        result = await ai_service.generate_flashcards(
            user_id=str(current_user.id),
            upload_id=upload_id,
            db_session=db
        )
        
        return FlashcardResponse(
            artifact_id=result["artifact_id"],
            flashcards=result["flashcards"]
        )
        
    except AIProcessingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/quiz/{upload_id}", response_model=QuizResponse)
async def generate_quiz(
    upload_id: str,
    quiz_type: str = Body("mcq", embed=True),
    num_questions: int = Body(10, embed=True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Generate quiz from document"""
    if current_user.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Only students can generate quizzes")
    
    try:
        # Verify upload belongs to user
        upload = await db.execute(
            select(Upload).where(
                and_(
                    Upload.id == upload_id,
                    Upload.user_id == str(current_user.id),
                    Upload.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")
        
        ai_service = AIService()
        result = await ai_service.generate_quiz(
            user_id=str(current_user.id),
            upload_id=upload_id,
            db_session=db,
            quiz_type=quiz_type,
            num_questions=num_questions
        )
        
        return QuizResponse(
            artifact_id=result["artifact_id"],
            quiz=result["quiz"]
        )
        
    except AIProcessingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


# AI Artifacts Endpoints
@router.get("/artifacts", response_model=List[AIArtifactResponse])
async def get_ai_artifacts(
    upload_id: Optional[str] = Query(None),
    artifact_type: Optional[AIArtifactType] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's AI artifacts"""
    try:
        query = select(AIArtifact).where(
            and_(
                AIArtifact.user_id == str(current_user.id),
                AIArtifact.deleted_at.is_(None)
            )
        )
        
        if upload_id:
            query = query.where(AIArtifact.upload_id == upload_id)
        
        if artifact_type:
            query = query.where(AIArtifact.type == artifact_type)
        
        query = query.order_by(AIArtifact.created_at.desc())
        
        artifacts = await db.execute(query).scalars().all()
        
        return [
            AIArtifactResponse(
                artifact_id=str(artifact.id),
                type=artifact.type.value,
                status=artifact.status.value,
                payload=artifact.payload,
                created_at=artifact.created_at.isoformat()
            )
            for artifact in artifacts
        ]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/artifacts/{artifact_id}", response_model=AIArtifactResponse)
async def get_ai_artifact(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get specific AI artifact"""
    try:
        artifact = await db.execute(
            select(AIArtifact).where(
                and_(
                    AIArtifact.id == artifact_id,
                    AIArtifact.user_id == str(current_user.id),
                    AIArtifact.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")
        
        return AIArtifactResponse(
            artifact_id=str(artifact.id),
            type=artifact.type.value,
            status=artifact.status.value,
            payload=artifact.payload,
            created_at=artifact.created_at.isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/artifacts/{artifact_id}")
async def delete_ai_artifact(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete AI artifact"""
    try:
        artifact = await db.execute(
            select(AIArtifact).where(
                and_(
                    AIArtifact.id == artifact_id,
                    AIArtifact.user_id == str(current_user.id),
                    AIArtifact.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")
        
        # Soft delete
        artifact.deleted_at = datetime.now(timezone.utc)
        await db.commit()
        
        return {"message": "Artifact deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


# Export Endpoints
@router.get("/export/flashcards/{artifact_id}")
async def export_flashcards_csv(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Export flashcards as CSV for Anki import"""
    try:
        # Verify artifact belongs to user
        artifact = await db.execute(
            select(AIArtifact).where(
                and_(
                    AIArtifact.id == artifact_id,
                    AIArtifact.user_id == str(current_user.id),
                    AIArtifact.type == AIArtifactType.FLASHCARDS,
                    AIArtifact.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        
        if not artifact:
            raise HTTPException(status_code=404, detail="Flashcard artifact not found")
        
        ai_service = AIService()
        csv_content = await ai_service.export_flashcards_csv(artifact_id, db)
        
        return {
            "csv_content": csv_content,
            "filename": f"flashcards_{artifact_id}.csv"
        }
        
    except AIProcessingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


# Usage and Limits Endpoints
@router.get("/usage")
async def get_ai_usage(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get AI usage statistics for user"""
    try:
        # TODO: Implement usage tracking
        # For now, return placeholder data
        return {
            "total_requests": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
            "monthly_usage": {
                "qa_requests": 0,
                "summaries_generated": 0,
                "flashcards_generated": 0,
                "quizzes_generated": 0
            },
            "limits": {
                "monthly_qa_requests": 100,
                "monthly_summaries": 20,
                "monthly_flashcards": 10,
                "monthly_quizzes": 5
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/chat")
async def chat_with_ai(
    message: dict = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Chat with AI using RAG on user's uploaded documents"""
    if current_user.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Only students can use AI chat")
    
    try:
        ai_service = AIService()
        
        # Get user's uploaded documents
        user_uploads = await db.execute(
            select(Upload).where(
                and_(
                    Upload.user_id == str(current_user.id),
                    Upload.processed == True
                )
            )
        )
        uploads = user_uploads.scalars().all()
        
        if not uploads:
            # If no documents uploaded, provide a general response
            response = await ai_service.chat_without_context(message.get("message", ""))
            return {
                "response": response,
                "sources": [],
                "has_documents": False
            }
        
        # Use RAG to answer based on user's documents
        response, sources = await ai_service.chat_with_rag(
            message.get("message", ""),
            str(current_user.id),
            db
        )
        
        return {
            "response": response,
            "sources": sources,
            "has_documents": True
        }
        
    except Exception as e:
        # logger.error(f"Error in AI chat: {str(e)}") # This line was not in the original file, so it's not added.
        raise HTTPException(status_code=500, detail="Error processing chat request")


@router.get("/chat/history")
async def get_chat_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get chat history for the current user"""
    if current_user.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Only students can access chat history")
    
    try:
        # Get recent chat messages (you can implement this based on your needs)
        # For now, return empty array - you can add a Message model later
        return []
        
    except Exception as e:
        # logger.error(f"Error fetching chat history: {str(e)}") # This line was not in the original file, so it's not added.
        raise HTTPException(status_code=500, detail="Error fetching chat history")
