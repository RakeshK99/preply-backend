# Preply AI Study Assistant & Payment Systems

## Overview

The Preply platform includes two major systems: an AI-powered study assistant for document processing and content generation, and a comprehensive payment system with subscription management and credit-based booking.

## AI Study Assistant System

### Architecture

#### Core Components
1. **AIService** - Main AI processing and content generation
2. **StorageService** - File upload and management (S3/Supabase)
3. **Document Processing Pipeline** - Text extraction and embedding
4. **Vector Search** - Pinecone integration for semantic search
5. **Content Generation** - OpenAI-powered summaries, flashcards, quizzes

#### Data Flow
```
Document Upload → Storage → Text Extraction → Embeddings → Pinecone
                                    ↓
                            Content Generation → AI Artifacts
                                    ↓
                            Semantic Q&A → RAG Response
```

### Document Processing Pipeline

#### 1. File Upload & Validation
- **Supported Formats**: PDF, DOCX, PPTX, TXT, MD, RTF, ODT
- **Size Limits**: 50MB maximum per file
- **Validation**: MIME type checking, file extension validation
- **Storage**: S3 or Supabase Storage with user-specific paths

#### 2. Text Extraction
- **PDF**: PyPDF for text extraction
- **Office Documents**: Unstructured library for DOCX/PPTX
- **Plain Text**: Direct UTF-8 decoding
- **Fallback**: Unstructured library for unsupported formats

#### 3. Text Processing
- **Chunking**: RecursiveCharacterTextSplitter (1000 chars, 200 overlap)
- **Metadata**: User ID, upload ID, chunk index, processing timestamp
- **Embeddings**: OpenAI ada-002 model (1536 dimensions)

#### 4. Vector Storage
- **Pinecone**: Per-user namespaces for data isolation
- **Indexing**: Cosine similarity for semantic search
- **Metadata**: Rich context for source attribution

### AI Features

#### 1. Semantic Q&A (RAG)
```python
# Example usage
response = await ai_service.semantic_qa(
    user_id="user_123",
    question="What are the main concepts in chapter 3?",
    upload_id="upload_456"
)
```

**Features:**
- **Retrieval-Augmented Generation**: Combines document search with LLM
- **Source Attribution**: Links answers to specific document chunks
- **Confidence Scoring**: Based on similarity scores
- **Context Window**: Handles large documents efficiently

#### 2. Document Summaries
```python
# Generate comprehensive summary
summary = await ai_service.generate_summary(
    user_id="user_123",
    upload_id="upload_456"
)
```

**Output Structure:**
```json
{
  "outline": "Detailed document outline with sections",
  "summary": "Comprehensive TL;DR summary",
  "key_takeaways": ["Point 1", "Point 2", "Point 3"]
}
```

#### 3. Flashcard Generation
```python
# Generate study flashcards
flashcards = await ai_service.generate_flashcards(
    user_id="user_123",
    upload_id="upload_456"
)
```

**Flashcard Structure:**
```json
{
  "front": "Question or concept",
  "back": "Detailed answer or explanation",
  "difficulty": "easy|medium|hard",
  "topic": "Main subject area"
}
```

**Export Options:**
- **CSV Format**: Anki-compatible import
- **JSON API**: Direct integration
- **PDF Export**: Printable format (future)

#### 4. Quiz Generation
```python
# Generate multiple choice quiz
quiz = await ai_service.generate_quiz(
    user_id="user_123",
    upload_id="upload_456",
    quiz_type="mcq",
    num_questions=10
)
```

**Quiz Structure:**
```json
{
  "quiz_type": "mcq",
  "questions": [
    {
      "question": "Question text",
      "options": ["A", "B", "C", "D"],
      "correct_answer": "Correct option",
      "explanation": "Detailed explanation",
      "difficulty": "easy|medium|hard"
    }
  ]
}
```

### Cost Management & Guardrails

#### 1. Usage Tracking
- **Token Counting**: Tiktoken for accurate token measurement
- **Cost Calculation**: Per-model pricing (GPT-4, ada-002)
- **Usage Limits**: Per-user and per-plan restrictions

#### 2. Content Filtering
- **Profanity Filter**: OpenAI content filtering
- **Safety Checks**: Automatic content moderation
- **Quality Thresholds**: Confidence-based filtering

#### 3. Rate Limiting
- **Request Limits**: Per-user and per-minute limits
- **Queue Management**: Background processing for large files
- **Error Handling**: Graceful degradation on failures

## Payment System

### Architecture

#### Core Components
1. **StripeService** - Payment processing and subscription management
2. **Credit System** - Ledger-based credit tracking
3. **Webhook Processing** - Real-time payment event handling
4. **Subscription Management** - Plan-based access control

#### Payment Models

#### 1. Subscription Model (Recommended)
```json
{
  "plans": {
    "starter": {
      "price": "$19/month",
      "ai_generations": 50,
      "booking_credits": 2,
      "features": ["Basic AI", "Email Support"]
    },
    "pro": {
      "price": "$49/month",
      "ai_generations": 200,
      "booking_credits": 5,
      "features": ["Advanced AI", "Priority Support", "Analytics"]
    },
    "premium": {
      "price": "$99/month",
      "ai_generations": "Unlimited",
      "booking_credits": 10,
      "features": ["All Features", "Dedicated Support"]
    }
  }
}
```

#### 2. Pay-as-You-Go Model
- **Per Session**: Direct payment for each tutoring session
- **Credit Packs**: Bulk purchase of session credits
- **Flexible Pricing**: Based on tutor rates or fixed pricing

#### 3. Hybrid Model
- **Subscription**: Unlocks AI features and discounted sessions
- **Top-ups**: Additional credits for heavy users
- **Flexibility**: Mix of subscription and one-time payments

### Credit System

#### 1. Credit Ledger
```sql
-- Credit ledger table
CREATE TABLE credit_ledger (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    delta INTEGER NOT NULL,  -- Positive for credits added, negative for used
    reason ENUM('subscription', 'credit_pack', 'booking', 'refund', 'manual'),
    balance_after INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### 2. Credit Operations
```python
# Add credits (subscription, purchase)
await stripe_service._add_credits(user_id, 5, "subscription")

# Deduct credits (booking)
success = await stripe_service.deduct_credits(user_id, 1, "booking")

# Check balance
balance = await get_credit_balance(user_id)
```

#### 3. Credit Pack Templates
```json
{
  "credit_packs": [
    {
      "id": "starter",
      "name": "Starter Pack",
      "credits": 5,
      "price_cents": 2500,
      "description": "Perfect for trying out tutoring sessions"
    },
    {
      "id": "popular",
      "name": "Popular Pack",
      "credits": 10,
      "price_cents": 4500,
      "description": "Most popular choice for regular students"
    },
    {
      "id": "premium",
      "name": "Premium Pack",
      "credits": 20,
      "price_cents": 8000,
      "description": "Best value for serious learners"
    }
  ]
}
```

### Stripe Integration

#### 1. Customer Management
```python
# Create Stripe customer
customer = await stripe_service.create_customer(user, db_session)

# Customer portal access
portal_url = await stripe_service.get_customer_portal_url(user, db_session)
```

#### 2. Subscription Management
```python
# Create subscription checkout
checkout = await stripe_service.create_subscription_checkout_session(
    user=user,
    price_id="price_starter",
    success_url="https://app.preply.com/success",
    cancel_url="https://app.preply.com/cancel"
)

# Cancel subscription
success = await stripe_service.cancel_subscription(user, db_session)
```

#### 3. Payment Processing
```python
# Create payment intent
intent = await stripe_service.create_payment_intent(
    user=user,
    amount_cents=5000,  # $50.00
    description="Tutoring session with John Doe",
    metadata={"booking_id": "booking_123"}
)

# Process credit pack purchase
checkout = await stripe_service.create_credit_pack_checkout(
    user=user,
    credit_amount=10,
    price_cents=4500,
    success_url="https://app.preply.com/success",
    cancel_url="https://app.preply.com/cancel"
)
```

#### 4. Webhook Processing
```python
# Handle webhook events
success = await stripe_service.process_webhook(payload, signature, db_session)

# Event types handled:
# - checkout.session.completed
# - customer.subscription.created/updated/deleted
# - invoice.payment_succeeded/failed
# - payment_intent.succeeded/failed
```

### API Endpoints

#### AI Endpoints
```http
# Document upload
POST /api/v1/ai/upload
Content-Type: multipart/form-data

# Semantic Q&A
POST /api/v1/ai/qa
{
  "question": "What are the main concepts?",
  "upload_id": "optional_upload_id"
}

# Generate content
POST /api/v1/ai/summary/{upload_id}
POST /api/v1/ai/flashcards/{upload_id}
POST /api/v1/ai/quiz/{upload_id}

# Manage artifacts
GET /api/v1/ai/artifacts
GET /api/v1/ai/artifacts/{artifact_id}
DELETE /api/v1/ai/artifacts/{artifact_id}

# Export
GET /api/v1/ai/export/flashcards/{artifact_id}
```

#### Payment Endpoints
```http
# Subscription management
GET /api/v1/payments/plans
POST /api/v1/payments/subscription/checkout
GET /api/v1/payments/subscriptions
POST /api/v1/payments/subscription/cancel
GET /api/v1/payments/customer-portal

# Payment processing
POST /api/v1/payments/payment-intent
POST /api/v1/payments/credit-pack/checkout

# Credit management
GET /api/v1/payments/credits/balance
GET /api/v1/payments/credits/ledger

# Payment history
GET /api/v1/payments/payments

# Webhook
POST /api/v1/payments/webhook
```

### Security & Compliance

#### 1. Data Protection
- **Encryption**: OAuth tokens encrypted at rest
- **Access Control**: Role-based API access
- **Audit Trail**: Complete payment and usage history

#### 2. Payment Security
- **PCI Compliance**: Stripe handles card data
- **Webhook Verification**: Signature validation
- **Idempotency**: Prevents duplicate processing

#### 3. AI Safety
- **Content Filtering**: Automatic moderation
- **Usage Limits**: Prevents abuse
- **Error Handling**: Graceful failures

### Monitoring & Analytics

#### 1. Key Metrics
- **AI Usage**: Requests, tokens, costs per user
- **Payment Success**: Conversion rates, failure reasons
- **Subscription Health**: Churn, upgrades, downgrades
- **Credit Utilization**: Balance trends, purchase patterns

#### 2. Cost Tracking
```python
# Track AI usage costs
cost = (total_tokens / 1000) * cost_per_1k_tokens[model]

# Monitor payment processing
success_rate = successful_payments / total_payments
```

#### 3. Alerting
- **High Usage**: Users approaching limits
- **Payment Failures**: Failed subscriptions or payments
- **System Health**: AI service availability

### Deployment Considerations

#### 1. Environment Variables
```bash
# AI Services
OPENAI_API_KEY=your-openai-key
PINECONE_API_KEY=your-pinecone-key
PINECONE_ENVIRONMENT=your-environment
PINECONE_INDEX_NAME=preply-documents

# Storage
STORAGE_TYPE=s3  # or supabase
AWS_ACCESS_KEY_ID=your-aws-key
AWS_SECRET_ACCESS_KEY=your-aws-secret
AWS_S3_BUCKET=preply-documents

# Stripe
STRIPE_SECRET_KEY=your-stripe-secret
STRIPE_WEBHOOK_SECRET=your-webhook-secret
```

#### 2. Scaling Strategy
- **AI Processing**: Background workers for document processing
- **Payment Processing**: Stripe handles payment scaling
- **Storage**: S3/Supabase for file storage scaling
- **Database**: Proper indexing for payment queries

#### 3. Backup & Recovery
- **Document Storage**: S3 versioning and cross-region replication
- **Payment Data**: Stripe backup and database replication
- **AI Artifacts**: Database backup and export capabilities

This comprehensive system provides a robust foundation for AI-powered education with flexible payment options, ensuring scalability and user satisfaction.
