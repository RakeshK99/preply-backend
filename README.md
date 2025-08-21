# Preply Backend - AI Study Assistant

A comprehensive FastAPI backend for Preply, an AI-powered study assistant platform with tutoring scheduling, payment processing, and intelligent document analysis.

## 🚀 Features

### Core Functionality
- **User Authentication & Authorization** - Secure user management with Clerk integration
- **Tutoring Scheduling System** - Complete booking and availability management
- **AI Study Assistant** - Document processing, Q&A, summaries, flashcards, and quizzes
- **Payment Processing** - Stripe integration with subscription and pay-as-you-go models
- **File Storage** - S3-compatible storage for document uploads
- **Email & SMS Notifications** - Automated communication system

### AI Study Assistant Features
- **Document Upload & Processing** - PDF, Word, PowerPoint, and text files
- **Semantic Q&A** - Ask questions about uploaded documents
- **Document Summaries** - Generate outlines and key takeaways
- **Flashcard Generation** - Create study cards with difficulty levels
- **Quiz Creation** - Multiple choice and short answer questions
- **Vector Search** - Pinecone integration for semantic document retrieval

### Payment & Subscription System
- **Subscription Plans** - Starter ($19.99), Pro ($39.99), Premium ($79.99)
- **Credit System** - Monthly credits and credit pack purchases
- **Pay-as-you-go** - One-time session payments
- **Stripe Integration** - Complete payment processing with webhooks

## 🛠 Tech Stack

- **Framework**: FastAPI 0.104.1
- **Database**: PostgreSQL with SQLAlchemy 2.0
- **Authentication**: Clerk
- **Payments**: Stripe
- **AI/ML**: OpenAI GPT-4, LangChain, Pinecone
- **File Storage**: S3/Supabase
- **Background Tasks**: Celery with Redis
- **Email**: Resend
- **Calendar**: Google Calendar API

## 📋 Prerequisites

- Python 3.8+
- PostgreSQL
- Redis
- Stripe account
- OpenAI API key
- Pinecone account
- S3-compatible storage

## 🚀 Quick Start

### 1. Clone the Repository
```bash
git clone https://github.com/RakeshK99/preply-backend.git
cd preply-backend
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Environment Setup
Create a `.env` file with the following variables:
```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost/preply

# Authentication
CLERK_SECRET_KEY=your_clerk_secret_key
CLERK_PUBLISHABLE_KEY=your_clerk_publishable_key

# OpenAI
OPENAI_API_KEY=your_openai_api_key

# Pinecone
PINECONE_API_KEY=your_pinecone_api_key
PINECONE_ENVIRONMENT=your_pinecone_environment
PINECONE_INDEX_NAME=preply-notes

# Stripe
STRIPE_SECRET_KEY=your_stripe_secret_key
STRIPE_PUBLISHABLE_KEY=your_stripe_publishable_key
STRIPE_WEBHOOK_SECRET=your_stripe_webhook_secret

# File Storage
S3_ACCESS_KEY_ID=your_s3_access_key
S3_SECRET_ACCESS_KEY=your_s3_secret_key
S3_BUCKET_NAME=preply-uploads
S3_REGION=us-east-1

# Email
RESEND_API_KEY=your_resend_api_key
FROM_EMAIL=noreply@preply.com

# Redis
REDIS_URL=your_redis_url
```

### 4. Database Setup
```bash
# Run migrations
alembic upgrade head
```

### 5. Start the Server
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## 📚 API Documentation

Once the server is running, visit:
- **Interactive API Docs**: http://localhost:8000/docs
- **ReDoc Documentation**: http://localhost:8000/redoc

## 🔧 Key Endpoints

### Authentication
- `POST /api/v1/auth/login` - User login
- `POST /api/v1/auth/register` - User registration
- `GET /api/v1/auth/me` - Get current user

### AI Study Assistant
- `POST /api/v1/ai/upload` - Upload documents
- `POST /api/v1/ai/qa` - Ask questions about documents
- `POST /api/v1/ai/summary/{upload_id}` - Generate document summaries
- `POST /api/v1/ai/flashcards/{upload_id}` - Create flashcards
- `POST /api/v1/ai/quiz/{upload_id}` - Generate quizzes

### Payments & Subscriptions
- `GET /api/v1/payments/plans` - Get subscription plans
- `POST /api/v1/payments/subscription/checkout` - Create subscription
- `GET /api/v1/payments/subscription/status` - Get subscription status
- `POST /api/v1/payments/credit-pack/checkout` - Purchase credit pack

### Scheduling
- `GET /api/v1/scheduling/availability` - Get tutor availability
- `POST /api/v1/scheduling/book` - Book a session
- `GET /api/v1/scheduling/bookings` - Get user bookings

## 🏗 Project Structure

```
preply_backend/
├── app/
│   ├── api/v1/
│   │   ├── endpoints/          # API endpoints
│   │   │   ├── ai.py          # AI study assistant
│   │   │   ├── auth.py        # Authentication
│   │   │   ├── payments.py    # Payment processing
│   │   │   └── scheduling.py  # Booking system
│   │   └── api.py             # API router
│   ├── core/
│   │   ├── config.py          # Configuration
│   │   ├── database.py        # Database setup
│   │   ├── pricing.py         # Pricing configuration
│   │   └── exceptions.py      # Custom exceptions
│   ├── models/                # Database models
│   │   ├── user.py           # User model
│   │   ├── ai_artifact.py    # AI generated content
│   │   ├── booking.py        # Booking model
│   │   └── payment.py        # Payment model
│   └── services/             # Business logic
│       ├── ai_service.py     # AI processing
│       ├── stripe_service.py # Payment processing
│       └── scheduling_service.py # Booking logic
├── alembic/                  # Database migrations
├── requirements.txt          # Python dependencies
└── main.py                  # Application entry point
```

## 🔒 Security Features

- **JWT Authentication** - Secure token-based authentication
- **Role-based Access Control** - Student, Tutor, and Admin roles
- **Input Validation** - Pydantic models for request validation
- **SQL Injection Protection** - SQLAlchemy ORM with parameterized queries
- **CORS Configuration** - Cross-origin resource sharing setup
- **Rate Limiting** - API rate limiting (configurable)

## 🧪 Testing

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=app
```

## 🚀 Deployment

### Docker Deployment
```bash
# Build image
docker build -t preply-backend .

# Run container
docker run -p 8000:8000 preply-backend
```

### Environment Variables
Make sure to set all required environment variables in your deployment environment.

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📞 Support

For support, email support@preply.com or create an issue in this repository.

---

**Built with ❤️ for students and tutors worldwide**
