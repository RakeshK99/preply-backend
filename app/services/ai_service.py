from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone
import asyncio
import json
import logging
from pathlib import Path
import tempfile
import os
from sqlalchemy import select

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import Pinecone
from langchain.chat_models import ChatOpenAI
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from langchain.schema import Document
from langchain.chains.question_answering import load_qa_chain
import pinecone
import openai
from pypdf import PdfReader
from unstructured.partition.auto import partition
import tiktoken

from app.core.config import settings
from app.core.pricing import get_ai_usage_limits
from app.models.upload import Upload, UploadOrigin
from app.models.ai_artifact import AIArtifact, AIArtifactType, AIArtifactStatus
from app.models.user import User
from app.models.stripe_models import StripeSubscription, SubscriptionStatus
from app.core.exceptions import AIProcessingError, FileUploadError
from app.services.storage_service import StorageService
from app.services.stripe_service import StripeService

logger = logging.getLogger(__name__)


class AIService:
    """Comprehensive AI service for document processing and content generation"""
    
    def __init__(self):
        self.openai_client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.embeddings = OpenAIEmbeddings(openai_api_key=settings.OPENAI_API_KEY)
        self.storage_service = StorageService()
        
        # Initialize Pinecone
        pinecone.init(
            api_key=settings.PINECONE_API_KEY,
            environment=settings.PINECONE_ENVIRONMENT
        )
        
        # Text splitter configuration
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len,
            separators=["\n\n", "\n", " ", ""]
        )
        
        # Tokenizer for cost calculation
        self.tokenizer = tiktoken.encoding_for_model("gpt-4")
        
        # Cost tracking
        self.cost_per_1k_tokens = {
            "gpt-4": 0.03,  # Input
            "gpt-4-turbo": 0.01,  # Input
            "text-embedding-ada-002": 0.0001  # Per 1K tokens
        }
    
    async def process_document_upload(
        self,
        upload: Upload,
        user_id: str,
        db_session
    ) -> bool:
        """Process uploaded document and create vector embeddings"""
        try:
            # Download file from storage
            file_content = await self.storage_service.download_file(upload.file_key)
            
            # Extract text based on file type
            text_content = await self._extract_text(file_content, upload.mime)
            
            if not text_content:
                raise AIProcessingError("No text content extracted from document")
            
            # Split text into chunks
            chunks = self.text_splitter.split_text(text_content)
            
            # Create documents with metadata
            documents = []
            for i, chunk in enumerate(chunks):
                doc = Document(
                    page_content=chunk,
                    metadata={
                        "user_id": user_id,
                        "upload_id": str(upload.id),
                        "file_key": upload.file_key,
                        "origin": upload.origin.value,
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                        "processed_at": datetime.now(timezone.utc).isoformat()
                    }
                )
                documents.append(doc)
            
            # Create embeddings and store in Pinecone
            namespace = f"user_{user_id}"
            await self._store_embeddings(documents, namespace)
            
            # Mark upload as processed
            upload.processed = True
            await db_session.commit()
            
            logger.info(f"Successfully processed document {upload.id} with {len(chunks)} chunks")
            return True
            
        except Exception as e:
            logger.error(f"Error processing document {upload.id}: {e}")
            upload.processed = False
            await db_session.commit()
            raise AIProcessingError(f"Failed to process document: {str(e)}")
    
    async def _extract_text(self, file_content: bytes, mime_type: str) -> str:
        """Extract text from different file types"""
        try:
            if mime_type == "application/pdf":
                return await self._extract_pdf_text(file_content)
            elif mime_type in ["text/plain", "text/markdown"]:
                return file_content.decode('utf-8')
            elif mime_type in ["application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                              "application/msword"]:
                return await self._extract_doc_text(file_content)
            elif mime_type in ["application/vnd.openxmlformats-officedocument.presentationml.presentation",
                              "application/vnd.ms-powerpoint"]:
                return await self._extract_ppt_text(file_content)
            else:
                # Use unstructured for other file types
                return await self._extract_unstructured_text(file_content)
        except Exception as e:
            logger.error(f"Error extracting text from {mime_type}: {e}")
            raise FileUploadError(f"Failed to extract text from file: {str(e)}")
    
    async def _extract_pdf_text(self, file_content: bytes) -> str:
        """Extract text from PDF using PyPDF"""
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
                temp_file.write(file_content)
                temp_file_path = temp_file.name
            
            try:
                reader = PdfReader(temp_file_path)
                text = ""
                for page in reader.pages:
                    text += page.extract_text() + "\n"
                return text
            finally:
                os.unlink(temp_file_path)
        except Exception as e:
            raise FileUploadError(f"Failed to extract PDF text: {str(e)}")
    
    async def _extract_doc_text(self, file_content: bytes) -> str:
        """Extract text from Word documents"""
        try:
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as temp_file:
                temp_file.write(file_content)
                temp_file_path = temp_file.name
            
            try:
                elements = partition(temp_file_path)
                text = "\n".join([str(element) for element in elements])
                return text
            finally:
                os.unlink(temp_file_path)
        except Exception as e:
            raise FileUploadError(f"Failed to extract Word document text: {str(e)}")
    
    async def _extract_ppt_text(self, file_content: bytes) -> str:
        """Extract text from PowerPoint presentations"""
        try:
            with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as temp_file:
                temp_file.write(file_content)
                temp_file_path = temp_file.name
            
            try:
                elements = partition(temp_file_path)
                text = "\n".join([str(element) for element in elements])
                return text
            finally:
                os.unlink(temp_file_path)
        except Exception as e:
            raise FileUploadError(f"Failed to extract PowerPoint text: {str(e)}")
    
    async def _extract_unstructured_text(self, file_content: bytes) -> str:
        """Extract text using unstructured library"""
        try:
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                temp_file.write(file_content)
                temp_file_path = temp_file.name
            
            try:
                elements = partition(temp_file_path)
                text = "\n".join([str(element) for element in elements])
                return text
            finally:
                os.unlink(temp_file_path)
        except Exception as e:
            raise FileUploadError(f"Failed to extract text using unstructured: {str(e)}")
    
    async def _store_embeddings(self, documents: List[Document], namespace: str):
        """Store document embeddings in Pinecone"""
        try:
            # Get or create index
            index_name = settings.PINECONE_INDEX_NAME
            if index_name not in pinecone.list_indexes():
                pinecone.create_index(
                    name=index_name,
                    dimension=1536,  # OpenAI ada-002 embedding dimension
                    metric="cosine"
                )
            
            index = pinecone.Index(index_name)
            
            # Create embeddings
            texts = [doc.page_content for doc in documents]
            metadatas = [doc.metadata for doc in documents]
            
            embeddings = await self.embeddings.aembed_documents(texts)
            
            # Prepare vectors for Pinecone
            vectors = []
            for i, (text, embedding, metadata) in enumerate(zip(texts, embeddings, metadatas)):
                vector = {
                    "id": f"{namespace}_{metadata['upload_id']}_{metadata['chunk_index']}",
                    "values": embedding,
                    "metadata": metadata
                }
                vectors.append(vector)
            
            # Upsert to Pinecone
            index.upsert(vectors=vectors, namespace=namespace)
            
            logger.info(f"Stored {len(vectors)} embeddings in namespace {namespace}")
            
        except Exception as e:
            logger.error(f"Error storing embeddings: {e}")
            raise AIProcessingError(f"Failed to store embeddings: {str(e)}")
    
    async def semantic_qa(
        self,
        user_id: str,
        question: str,
        upload_id: Optional[str] = None,
        max_tokens: int = 1000,
        db_session = None
    ) -> Dict[str, Any]:
        """Perform semantic Q&A over user's documents"""
        try:
            # Check user's AI usage limits
            await self._check_usage_limits(user_id, "qa", db_session)
            
            namespace = f"user_{user_id}"
            
            # Get relevant documents from Pinecone
            index = pinecone.Index(settings.PINECONE_INDEX_NAME)
            
            # Create query embedding
            query_embedding = await self.embeddings.aembed_query(question)
            
            # Search for relevant documents
            filter_dict = {"user_id": user_id}
            if upload_id:
                filter_dict["upload_id"] = upload_id
            
            search_results = index.query(
                vector=query_embedding,
                top_k=5,
                include_metadata=True,
                namespace=namespace,
                filter=filter_dict
            )
            
            if not search_results.matches:
                return {
                    "answer": "I don't have enough information to answer this question based on your uploaded documents.",
                    "sources": [],
                    "confidence": 0.0
                }
            
            # Prepare context from search results
            context = "\n\n".join([match.metadata.get("page_content", "") for match in search_results.matches])
            
            # Create prompt for Q&A
            prompt_template = PromptTemplate(
                input_variables=["context", "question"],
                template="""
                Based on the following context from the user's documents, answer the question.
                If the answer cannot be found in the context, say "I don't have enough information to answer this question."
                
                Context:
                {context}
                
                Question: {question}
                
                Answer:"""
            )
            
            # Generate answer using OpenAI
            llm = ChatOpenAI(
                model="gpt-4",
                temperature=0.1,
                max_tokens=max_tokens,
                openai_api_key=settings.OPENAI_API_KEY
            )
            
            chain = load_qa_chain(llm, chain_type="stuff", prompt=prompt_template)
            
            # Create documents for the chain
            docs = [Document(page_content=context, metadata={})]
            
            result = await chain.arun({
                "input_documents": docs,
                "question": question
            })
            
            # Calculate confidence based on similarity scores
            confidence = sum([match.score for match in search_results.matches]) / len(search_results.matches)
            
            # Track usage
            await self._track_usage(user_id, "qa", len(result), len(context))
            
            return {
                "answer": result,
                "sources": [
                    {
                        "upload_id": match.metadata.get("upload_id"),
                        "chunk_index": match.metadata.get("chunk_index"),
                        "similarity": match.score
                    }
                    for match in search_results.matches
                ],
                "confidence": confidence
            }
            
        except Exception as e:
            logger.error(f"Error in semantic Q&A: {e}")
            raise AIProcessingError(f"Failed to perform semantic Q&A: {str(e)}")
    
    async def generate_summary(
        self,
        user_id: str,
        upload_id: str,
        db_session
    ) -> Dict[str, Any]:
        """Generate document summary with outline and TL;DR"""
        try:
            # Check user's AI usage limits
            await self._check_usage_limits(user_id, "summary", db_session)
            
            # Get document content from Pinecone
            namespace = f"user_{user_id}"
            index = pinecone.Index(settings.PINECONE_INDEX_NAME)
            
            # Get all chunks for this upload
            search_results = index.query(
                vector=[0] * 1536,  # Dummy vector to get all documents
                top_k=1000,
                include_metadata=True,
                namespace=namespace,
                filter={"upload_id": upload_id}
            )
            
            if not search_results.matches:
                raise AIProcessingError("No document content found")
            
            # Combine all chunks
            full_text = "\n\n".join([match.metadata.get("page_content", "") for match in search_results.matches])
            
            # Generate summary using OpenAI
            llm = ChatOpenAI(
                model="gpt-4",
                temperature=0.1,
                max_tokens=2000,
                openai_api_key=settings.OPENAI_API_KEY
            )
            
            summary_prompt = f"""
            Please analyze the following document and provide:
            
            1. A detailed outline with main sections and subsections
            2. A comprehensive summary (TL;DR) covering all key points
            3. Key takeaways and important concepts
            
            Document:
            {full_text[:8000]}  # Limit to first 8000 chars to stay within token limits
            
            Please format your response as JSON:
            {{
                "outline": "Detailed outline here",
                "summary": "Comprehensive summary here",
                "key_takeaways": ["Takeaway 1", "Takeaway 2", "Takeaway 3"]
            }}
            """
            
            response = await llm.agenerate([[summary_prompt]])
            result_text = response.generations[0][0].text
            
            # Parse JSON response
            try:
                summary_data = json.loads(result_text)
            except json.JSONDecodeError:
                # Fallback if JSON parsing fails
                summary_data = {
                    "outline": "Outline generation failed",
                    "summary": result_text,
                    "key_takeaways": ["Key takeaways could not be parsed"]
                }
            
            # Save to ai_artifacts
            artifact = AIArtifact(
                user_id=user_id,
                upload_id=upload_id,
                type=AIArtifactType.SUMMARY,
                payload=summary_data,
                status=AIArtifactStatus.COMPLETED
            )
            
            db_session.add(artifact)
            await db_session.commit()
            
            # Track usage
            await self._track_usage(user_id, "summary", len(result_text), len(full_text))
            
            return {
                "artifact_id": str(artifact.id),
                "summary": summary_data
            }
            
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            raise AIProcessingError(f"Failed to generate summary: {str(e)}")
    
    async def generate_flashcards(
        self,
        user_id: str,
        upload_id: str,
        db_session
    ) -> Dict[str, Any]:
        """Generate flashcards from document content"""
        try:
            # Check user's AI usage limits
            await self._check_usage_limits(user_id, "flashcards", db_session)
            
            # Get document content from Pinecone
            namespace = f"user_{user_id}"
            index = pinecone.Index(settings.PINECONE_INDEX_NAME)
            
            search_results = index.query(
                vector=[0] * 1536,
                top_k=1000,
                include_metadata=True,
                namespace=namespace,
                filter={"upload_id": upload_id}
            )
            
            if not search_results.matches:
                raise AIProcessingError("No document content found")
            
            full_text = "\n\n".join([match.metadata.get("page_content", "") for match in search_results.matches])
            
            # Generate flashcards using OpenAI
            llm = ChatOpenAI(
                model="gpt-4",
                temperature=0.1,
                max_tokens=3000,
                openai_api_key=settings.OPENAI_API_KEY
            )
            
            flashcard_prompt = f"""
            Create 10-15 flashcards from the following document content.
            Each flashcard should have a clear question on the front and a comprehensive answer on the back.
            Include difficulty levels (easy, medium, hard) based on the complexity of the concept.
            
            Document:
            {full_text[:6000]}
            
            Please format your response as JSON:
            {{
                "flashcards": [
                    {{
                        "front": "Question here",
                        "back": "Answer here",
                        "difficulty": "easy|medium|hard",
                        "topic": "Main topic this covers"
                    }}
                ]
            }}
            """
            
            response = await llm.agenerate([[flashcard_prompt]])
            result_text = response.generations[0][0].text
            
            # Parse JSON response
            try:
                flashcard_data = json.loads(result_text)
            except json.JSONDecodeError:
                flashcard_data = {
                    "flashcards": [
                        {
                            "front": "Error parsing flashcards",
                            "back": "Please try again",
                            "difficulty": "easy",
                            "topic": "Error"
                        }
                    ]
                }
            
            # Save to ai_artifacts
            artifact = AIArtifact(
                user_id=user_id,
                upload_id=upload_id,
                type=AIArtifactType.FLASHCARDS,
                payload=flashcard_data,
                status=AIArtifactStatus.COMPLETED
            )
            
            db_session.add(artifact)
            await db_session.commit()
            
            # Track usage
            await self._track_usage(user_id, "flashcards", len(result_text), len(full_text))
            
            return {
                "artifact_id": str(artifact.id),
                "flashcards": flashcard_data["flashcards"]
            }
            
        except Exception as e:
            logger.error(f"Error generating flashcards: {e}")
            raise AIProcessingError(f"Failed to generate flashcards: {str(e)}")
    
    async def generate_quiz(
        self,
        user_id: str,
        upload_id: str,
        db_session,
        quiz_type: str = "mcq",
        num_questions: int = 10
    ) -> Dict[str, Any]:
        """Generate quiz questions from document content"""
        try:
            # Check user's AI usage limits
            await self._check_usage_limits(user_id, "quiz", db_session)
            
            # Get document content from Pinecone
            namespace = f"user_{user_id}"
            index = pinecone.Index(settings.PINECONE_INDEX_NAME)
            
            search_results = index.query(
                vector=[0] * 1536,
                top_k=1000,
                include_metadata=True,
                namespace=namespace,
                filter={"upload_id": upload_id}
            )
            
            if not search_results.matches:
                raise AIProcessingError("No document content found")
            
            full_text = "\n\n".join([match.metadata.get("page_content", "") for match in search_results.matches])
            
            # Generate quiz using OpenAI
            llm = ChatOpenAI(
                model="gpt-4",
                temperature=0.1,
                max_tokens=4000,
                openai_api_key=settings.OPENAI_API_KEY
            )
            
            quiz_prompt = f"""
            Create a {quiz_type.upper()} quiz with {num_questions} questions from the following document content.
            
            Document:
            {full_text[:6000]}
            
            For each question, provide:
            - The question
            - Multiple choice options (A, B, C, D) if MCQ
            - The correct answer
            - A detailed explanation/rationale
            - Difficulty level (easy, medium, hard)
            
            Please format your response as JSON:
            {{
                "quiz_type": "{quiz_type}",
                "questions": [
                    {{
                        "question": "Question text here",
                        "options": ["A", "B", "C", "D"] if MCQ,
                        "correct_answer": "Correct answer",
                        "explanation": "Detailed explanation",
                        "difficulty": "easy|medium|hard"
                    }}
                ]
            }}
            """
            
            response = await llm.agenerate([[quiz_prompt]])
            result_text = response.generations[0][0].text
            
            # Parse JSON response
            try:
                quiz_data = json.loads(result_text)
            except json.JSONDecodeError:
                quiz_data = {
                    "quiz_type": quiz_type,
                    "questions": [
                        {
                            "question": "Error parsing quiz",
                            "correct_answer": "Please try again",
                            "explanation": "Quiz generation failed",
                            "difficulty": "easy"
                        }
                    ]
                }
            
            # Save to ai_artifacts
            artifact = AIArtifact(
                user_id=user_id,
                upload_id=upload_id,
                type=AIArtifactType.QUIZ,
                payload=quiz_data,
                status=AIArtifactStatus.COMPLETED
            )
            
            db_session.add(artifact)
            await db_session.commit()
            
            # Track usage
            await self._track_usage(user_id, "quiz", len(result_text), len(full_text))
            
            return {
                "artifact_id": str(artifact.id),
                "quiz": quiz_data
            }
            
        except Exception as e:
            logger.error(f"Error generating quiz: {e}")
            raise AIProcessingError(f"Failed to generate quiz: {str(e)}")
    
    async def _check_usage_limits(self, user_id: str, feature: str, db_session):
        """Check if user has exceeded AI usage limits"""
        try:
            # Get user's subscription status
            stripe_service = StripeService()
            subscription_status = await stripe_service.get_user_subscription_status(user_id, db_session)
            
            # Get AI limits for the user's plan
            plan_key = subscription_status.get("plan_key", "free")
            ai_limits = get_ai_usage_limits(plan_key)
            
            # Get the limit for this feature
            limit_key = f"{feature}_per_month"
            limit = getattr(ai_limits, limit_key, 0)
            
            # -1 means unlimited
            if limit == -1:
                return True
            
            # TODO: Implement actual usage tracking in database
            # For now, we'll allow usage (this should be implemented with a usage tracking table)
            # current_usage = await self._get_current_month_usage(user_id, feature, db_session)
            # if current_usage >= limit:
            #     raise AIProcessingError(f"Monthly limit exceeded for {feature}. Limit: {limit}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking usage limits for user {user_id}: {e}")
            raise AIProcessingError(f"Failed to check usage limits: {str(e)}")
    
    async def _track_usage(self, user_id: str, feature: str, output_tokens: int, input_tokens: int):
        """Track AI usage for cost calculation and limits"""
        # TODO: Implement usage tracking in database
        # Calculate cost and store usage metrics
        total_tokens = input_tokens + output_tokens
        cost = (total_tokens / 1000) * self.cost_per_1k_tokens["gpt-4"]
        
        logger.info(f"AI usage tracked for user {user_id}: {feature}, tokens: {total_tokens}, cost: ${cost:.4f}")
    
    async def export_flashcards_csv(self, artifact_id: str, db_session) -> str:
        """Export flashcards as CSV for Anki import"""
        try:
            artifact = await db_session.execute(
                select(AIArtifact).where(AIArtifact.id == artifact_id)
            ).scalar_one_or_none()
            
            if not artifact or artifact.type != AIArtifactType.FLASHCARDS:
                raise AIProcessingError("Flashcard artifact not found")
            
            flashcards = artifact.payload.get("flashcards", [])
            
            # Create CSV content
            csv_content = "Front,Back,Difficulty,Topic\n"
            for card in flashcards:
                front = card.get("front", "").replace('"', '""')  # Escape quotes
                back = card.get("back", "").replace('"', '""')
                difficulty = card.get("difficulty", "")
                topic = card.get("topic", "")
                
                csv_content += f'"{front}","{back}","{difficulty}","{topic}"\n'
            
            return csv_content
            
        except Exception as e:
            logger.error(f"Error exporting flashcards: {e}")
            raise AIProcessingError(f"Failed to export flashcards: {str(e)}")
    
    async def delete_document_embeddings(self, user_id: str, upload_id: str):
        """Delete document embeddings from Pinecone"""
        try:
            namespace = f"user_{user_id}"
            index = pinecone.Index(settings.PINECONE_INDEX_NAME)
            
            # Delete vectors for this upload
            index.delete(
                filter={"upload_id": upload_id},
                namespace=namespace
            )
            
            logger.info(f"Deleted embeddings for upload {upload_id} in namespace {namespace}")
            
        except Exception as e:
            logger.error(f"Error deleting embeddings: {e}")
            raise AIProcessingError(f"Failed to delete embeddings: {str(e)}")

    async def chat_with_rag(
        self,
        message: str,
        user_id: str,
        db_session
    ) -> Tuple[str, List[dict]]:
        """Chat with AI using RAG on user's documents"""
        try:
            # Get user's vector store
            index_name = f"user-{user_id}"
            
            # Check if index exists
            if index_name not in pinecone.list_indexes():
                # Create index if it doesn't exist
                pinecone.create_index(
                    name=index_name,
                    dimension=1536,  # OpenAI embedding dimension
                    metric="cosine"
                )
            
            # Get the vector store
            vectorstore = Pinecone.from_existing_index(
                index_name=index_name,
                embedding=self.embeddings
            )
            
            # Create retriever
            retriever = vectorstore.as_retriever(
                search_type="similarity",
                search_kwargs={"k": 5}
            )
            
            # Get relevant documents
            docs = retriever.get_relevant_documents(message)
            
            # Create context from documents
            context = "\n\n".join([doc.page_content for doc in docs])
            
            # Create prompt
            prompt = f"""You are a helpful AI tutor. Answer the student's question based on their uploaded study materials.

Context from student's documents:
{context}

Student's question: {message}

Please provide a clear, helpful answer based on the context. If the context doesn't contain enough information to answer the question, say so and provide general guidance.

Answer:"""
            
            # Get response from OpenAI
            response = await self.openai_client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a helpful AI tutor. Answer questions based on the provided context."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1000,
                temperature=0.7
            )
            
            # Extract sources
            sources = []
            for doc in docs:
                if hasattr(doc, 'metadata'):
                    sources.append({
                        "content": doc.page_content[:200] + "...",
                        "file": doc.metadata.get("file_key", "Unknown"),
                        "chunk_index": doc.metadata.get("chunk_index", 0)
                    })
            
            return response.choices[0].message.content, sources
            
        except Exception as e:
            logger.error(f"Error in RAG chat: {str(e)}")
            raise AIProcessingError(f"Error processing chat request: {str(e)}")

    async def chat_without_context(self, message: str) -> str:
        """Chat with AI without user documents (general responses)"""
        try:
            response = await self.openai_client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a helpful AI tutor. Provide general educational guidance and encourage students to upload their study materials for more specific help."},
                    {"role": "user", "content": message}
                ],
                max_tokens=500,
                temperature=0.7
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Error in general chat: {str(e)}")
            raise AIProcessingError(f"Error processing chat request: {str(e)}")
