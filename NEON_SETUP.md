# Neon Database Setup Guide

## 🚀 Quick Setup

### 1. Create Neon Database

1. Go to [Neon Console](https://console.neon.tech/)
2. Sign up/Login with your account
3. Create a new project
4. Choose a region close to your users
5. Copy the connection string

### 2. Update Environment Variables

Create a `.env` file in the backend root with:

```bash
# Database (Neon)
DATABASE_URL=postgresql+asyncpg://your-neon-connection-string

# Clerk Integration
CLERK_SECRET_KEY=sk_test_TUjvKWQlQfPtvTLEgQZ7WV4hD5VNa9bKgdKGA9ODyA
CLERK_PUBLISHABLE_KEY=pk_test_Y2xvc2UtY2FyZGluYWwtMjcuY2xlcmsuYWNjb3VudHMuZGV2JA

# Other required variables...
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Run Database Migrations

```bash
# Create tables
alembic upgrade head

# Or if using SQLAlchemy directly
python -c "from app.core.database import engine; from app.models import Base; Base.metadata.create_all(bind=engine)"
```

## 🔧 Neon Features

### Connection Pooling
Neon provides automatic connection pooling. Update your database URL to include pool settings:

```python
# In app/core/database.py
DATABASE_URL = "postgresql+asyncpg://user:password@host/dbname?sslmode=require&pool_size=10&max_overflow=20"
```

### Branching
Neon supports database branching for development:

```bash
# Create a development branch
neon branch create dev-branch

# Switch to branch
neon branch switch dev-branch
```

### Monitoring
- Monitor query performance in Neon Console
- Set up alerts for slow queries
- View connection usage

## 🛠️ Development Commands

```bash
# Start backend server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run database migrations
alembic upgrade head

# Create new migration
alembic revision --autogenerate -m "description"

# Rollback migration
alembic downgrade -1
```

## 🔒 Security

### SSL Connection
Neon requires SSL connections. The connection string should include:
```
?sslmode=require
```

### Connection String Format
```
postgresql+asyncpg://user:password@host/dbname?sslmode=require
```

## 📊 Performance Tips

1. **Connection Pooling**: Use appropriate pool sizes
2. **Indexing**: Create indexes on frequently queried columns
3. **Query Optimization**: Monitor slow queries in Neon Console
4. **Caching**: Use Redis for frequently accessed data

## 🚨 Troubleshooting

### Common Issues

1. **Connection Errors**
   - Check SSL mode is set to 'require'
   - Verify connection string format
   - Ensure database exists

2. **Migration Errors**
   - Check if tables already exist
   - Verify model definitions
   - Check for conflicting migrations

3. **Performance Issues**
   - Monitor query performance in Neon Console
   - Check connection pool settings
   - Review indexing strategy

## 📚 Resources

- [Neon Documentation](https://neon.tech/docs)
- [SQLAlchemy Async](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Alembic Migrations](https://alembic.sqlalchemy.org/)
