# Preply Database Schema

## Overview

This document describes the optimized, scalable database schema for Preply - AI Study Assistant. The schema is designed for high performance, data integrity, and future scalability.

## Design Principles

- **UUID Primary Keys**: All tables use UUID primary keys for better distribution and security
- **Soft Deletes**: Implemented via `deleted_at` timestamp for data retention
- **Audit Trail**: Comprehensive audit logging for all system changes
- **Normalized Design**: Proper normalization to prevent data redundancy
- **Indexing Strategy**: Strategic indexes for performance optimization
- **Timezone Awareness**: All timestamps stored in UTC with timezone support

## Core Tables

### 1. users
**Purpose**: Core user table with authentication and role management

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_provider_id VARCHAR NOT NULL UNIQUE,  -- Clerk user ID
    role ENUM('student', 'tutor', 'admin') NOT NULL DEFAULT 'student',
    name VARCHAR NOT NULL,
    email VARCHAR NOT NULL UNIQUE,
    timezone VARCHAR NOT NULL DEFAULT 'UTC',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ  -- Soft delete
);
```

**Indexes**:
- `idx_users_auth_provider_id` (UNIQUE)
- `idx_users_email` (UNIQUE)
- `idx_users_role` (for role-based queries)

### 2. tutor_profiles
**Purpose**: Extended profile information for tutors

```sql
CREATE TABLE tutor_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    bio TEXT,
    subjects TEXT[] NOT NULL DEFAULT '{}',  -- Array of subject strings
    hourly_rate_cents INTEGER NOT NULL,  -- Rate in cents
    meeting_link VARCHAR,  -- Default meeting link
    calendar_connected BOOLEAN NOT NULL DEFAULT FALSE,
    google_calendar_primary_id VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);
```

**Indexes**:
- `idx_tutor_profiles_user_id` (UNIQUE)
- `idx_tutor_profiles_subjects` (GIN for array searches)

### 3. student_profiles
**Purpose**: Extended profile information for students

```sql
CREATE TABLE student_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    school VARCHAR,
    grade VARCHAR,  -- e.g., "10th grade", "Sophomore"
    goals TEXT,  -- Learning goals
    calendar_connected BOOLEAN NOT NULL DEFAULT FALSE,
    google_calendar_primary_id VARCHAR,
    credit_balance INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);
```

**Indexes**:
- `idx_student_profiles_user_id` (UNIQUE)
- `idx_student_profiles_credit_balance` (for credit queries)

## Availability & Scheduling

### 4. availability_blocks
**Purpose**: Tutor availability windows with recurring support

```sql
CREATE TABLE availability_blocks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tutor_id UUID NOT NULL REFERENCES users(id),
    start_at TIMESTAMPTZ NOT NULL,  -- UTC
    end_at TIMESTAMPTZ NOT NULL,  -- UTC
    rrule TEXT,  -- iCalendar RRULE string
    is_recurring BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);
```

**Indexes**:
- `idx_availability_blocks_tutor_id`
- `idx_availability_blocks_start_at`
- `idx_availability_blocks_tutor_start` (tutor_id, start_at)

### 5. time_off_blocks
**Purpose**: Blackout periods for tutors

```sql
CREATE TABLE time_off_blocks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tutor_id UUID NOT NULL REFERENCES users(id),
    start_at TIMESTAMPTZ NOT NULL,  -- UTC
    end_at TIMESTAMPTZ NOT NULL,  -- UTC
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);
```

**Indexes**:
- `idx_time_off_blocks_tutor_id`
- `idx_time_off_blocks_start_at`

### 6. slots
**Purpose**: Bookable time slots (materialized from availability)

```sql
CREATE TABLE slots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tutor_id UUID NOT NULL REFERENCES users(id),
    start_at TIMESTAMPTZ NOT NULL,  -- UTC
    end_at TIMESTAMPTZ NOT NULL,  -- UTC
    status ENUM('open', 'held', 'booked', 'closed') NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);
```

**Indexes**:
- `idx_slots_tutor_start_unique` (UNIQUE on tutor_id, start_at) - **Prevents double-booking**
- `idx_slots_status`
- `idx_slots_start_at`

## Bookings & Sessions

### 7. bookings
**Purpose**: Session bookings between students and tutors

```sql
CREATE TABLE bookings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL REFERENCES users(id),
    tutor_id UUID NOT NULL REFERENCES users(id),
    start_at TIMESTAMPTZ NOT NULL,  -- UTC
    end_at TIMESTAMPTZ NOT NULL,  -- UTC
    status ENUM('pending_payment', 'confirmed', 'canceled', 'completed', 'refunded') NOT NULL DEFAULT 'pending_payment',
    price_cents INTEGER NOT NULL,
    payment_intent_id VARCHAR,
    calendar_event_id_student VARCHAR,
    calendar_event_id_tutor VARCHAR,
    join_link VARCHAR,
    notes TEXT,
    slot_id UUID REFERENCES slots(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);
```

**Indexes**:
- `idx_bookings_student_id`
- `idx_bookings_tutor_id`
- `idx_bookings_start_at`
- `idx_bookings_status`
- `idx_bookings_payment_intent_id` (UNIQUE)

## External Integrations

### 8. google_oauth_accounts
**Purpose**: Google OAuth tokens for calendar integration

```sql
CREATE TABLE google_oauth_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    provider VARCHAR NOT NULL DEFAULT 'google',
    access_token TEXT NOT NULL,  -- Encrypted
    refresh_token TEXT,  -- Encrypted
    expiry TIMESTAMPTZ,
    scopes TEXT,  -- JSON string
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);
```

**Indexes**:
- `idx_google_oauth_accounts_user_id`
- `idx_google_oauth_accounts_provider`

### 9. stripe_customers
**Purpose**: Stripe customer mapping

```sql
CREATE TABLE stripe_customers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) UNIQUE,
    stripe_customer_id VARCHAR NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);
```

### 10. stripe_subscriptions
**Purpose**: Stripe subscription management

```sql
CREATE TABLE stripe_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    stripe_subscription_id VARCHAR NOT NULL UNIQUE,
    status ENUM('active', 'canceled', 'past_due', 'unpaid', 'trial') NOT NULL,
    current_period_end TIMESTAMPTZ,
    plan_key VARCHAR NOT NULL,  -- e.g., "starter", "pro"
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);
```

**Indexes**:
- `idx_stripe_subscriptions_user_id`
- `idx_stripe_subscriptions_status`

## Payment & Credits

### 11. payments
**Purpose**: Payment transaction tracking

```sql
CREATE TABLE payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    booking_id UUID REFERENCES bookings(id),
    stripe_payment_intent_id VARCHAR NOT NULL UNIQUE,
    amount_cents INTEGER NOT NULL,
    type ENUM('subscription', 'one_off', 'credit_pack') NOT NULL,
    status ENUM('pending', 'succeeded', 'failed', 'refunded') NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);
```

**Indexes**:
- `idx_payments_user_id`
- `idx_payments_booking_id`
- `idx_payments_status`
- `idx_payments_type`

### 12. credit_ledger
**Purpose**: Credit transaction history and balance tracking

```sql
CREATE TABLE credit_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    delta INTEGER NOT NULL,  -- Positive or negative change
    reason ENUM('purchase', 'booking', 'refund', 'manual') NOT NULL,
    booking_id UUID REFERENCES bookings(id),
    balance_after INTEGER NOT NULL,  -- Running balance
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);
```

**Indexes**:
- `idx_credit_ledger_user_id`
- `idx_credit_ledger_booking_id`
- `idx_credit_ledger_reason`

## Content & AI

### 13. uploads
**Purpose**: File upload management

```sql
CREATE TABLE uploads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    file_key VARCHAR NOT NULL,  -- S3 key
    mime VARCHAR NOT NULL,
    bytes INTEGER NOT NULL,
    origin ENUM('notes', 'slides', 'assignment') NOT NULL,
    processed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);
```

**Indexes**:
- `idx_uploads_user_id`
- `idx_uploads_origin`
- `idx_uploads_processed`

### 14. ai_artifacts
**Purpose**: AI-generated content storage

```sql
CREATE TABLE ai_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    upload_id UUID REFERENCES uploads(id),
    type ENUM('flashcards', 'quiz', 'summary') NOT NULL,
    payload JSONB NOT NULL,  -- Generated content
    status ENUM('pending', 'processing', 'completed', 'failed') NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);
```

**Indexes**:
- `idx_ai_artifacts_user_id`
- `idx_ai_artifacts_upload_id`
- `idx_ai_artifacts_type`
- `idx_ai_artifacts_status`
- `idx_ai_artifacts_payload` (GIN for JSON queries)

### 15. messages
**Purpose**: AI chat message history

```sql
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    role ENUM('user', 'assistant', 'system') NOT NULL,
    content TEXT NOT NULL,
    thread_id VARCHAR NOT NULL,  -- Conversation grouping
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);
```

**Indexes**:
- `idx_messages_user_id`
- `idx_messages_thread_id`
- `idx_messages_role`

## System & Audit

### 16. notifications
**Purpose**: User notification management

```sql
CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    type ENUM('booking_confirmation', 'booking_reminder', 'booking_cancellation', 'payment_success', 'payment_failed', 'credit_low', 'ai_artifact_ready', 'system_update') NOT NULL,
    payload JSONB NOT NULL,  -- Notification content
    delivery ENUM('email', 'sms', 'inapp') NOT NULL,
    status ENUM('pending', 'sent', 'failed', 'read') NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);
```

**Indexes**:
- `idx_notifications_user_id`
- `idx_notifications_type`
- `idx_notifications_status`
- `idx_notifications_delivery`

### 17. audit_log
**Purpose**: Comprehensive system audit trail

```sql
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_user_id UUID REFERENCES users(id),  -- NULL for system actions
    action VARCHAR NOT NULL,  -- e.g., "create", "update", "delete"
    entity VARCHAR NOT NULL,  -- e.g., "user", "booking"
    entity_id VARCHAR,  -- Affected entity ID
    diff JSONB,  -- Before/after values
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);
```

**Indexes**:
- `idx_audit_log_actor_user_id`
- `idx_audit_log_action`
- `idx_audit_log_entity`
- `idx_audit_log_entity_id`
- `idx_audit_log_created_at`

## Key Design Decisions

### 1. UUID Primary Keys
- **Benefits**: Better distribution, security, no sequential guessing
- **Performance**: Slightly slower than integers but acceptable for scale
- **Migration**: Easier to merge databases or shard in the future

### 2. Soft Deletes
- **Implementation**: `deleted_at` timestamp column
- **Benefits**: Data retention, audit compliance, easy recovery
- **Queries**: Always filter by `WHERE deleted_at IS NULL`

### 3. UTC Timestamps
- **Storage**: All timestamps in UTC
- **Display**: Convert to user timezone in application layer
- **Benefits**: Consistent time handling, easier scheduling

### 4. JSONB for Flexible Data
- **Usage**: AI artifacts, notifications, audit diffs
- **Benefits**: Schema flexibility, efficient querying
- **Indexing**: GIN indexes for performance

### 5. Credit System
- **Implementation**: Ledger pattern with running balance
- **Benefits**: Audit trail, easy reconciliation, complex transactions
- **Performance**: Balance queries are fast with proper indexing

### 6. Calendar Integration
- **Approach**: Store Google Calendar event IDs
- **Benefits**: Bidirectional sync, conflict resolution
- **Security**: Encrypted OAuth tokens

## Performance Considerations

### Indexing Strategy
- **Primary Keys**: UUID with default gen_random_uuid()
- **Foreign Keys**: Indexed for join performance
- **Query Patterns**: Indexes on frequently queried columns
- **Composite Indexes**: For complex queries (e.g., tutor_id + start_at)

### Partitioning Strategy
- **Audit Log**: Partition by date for large volumes
- **Messages**: Partition by thread_id for chat history
- **Bookings**: Partition by date for historical data

### Scaling Considerations
- **Read Replicas**: For analytics and reporting
- **Sharding**: By user_id for horizontal scaling
- **Caching**: Redis for frequently accessed data
- **Archiving**: Move old data to cheaper storage

## Migration Strategy

### Phase 1: Core Tables
1. users, tutor_profiles, student_profiles
2. availability_blocks, time_off_blocks, slots
3. bookings

### Phase 2: Integrations
1. google_oauth_accounts
2. stripe_customers, stripe_subscriptions
3. payments, credit_ledger

### Phase 3: Content & AI
1. uploads, ai_artifacts
2. messages

### Phase 4: System
1. notifications
2. audit_log

## Security Considerations

### Data Protection
- **Encryption**: OAuth tokens encrypted at rest
- **Access Control**: Row-level security where appropriate
- **Audit Trail**: All changes logged with actor information

### Compliance
- **GDPR**: Soft deletes enable data retention policies
- **PCI DSS**: Payment data handled by Stripe
- **FERPA**: Educational data protection measures

This schema provides a solid foundation for a scalable, production-ready edtech platform with comprehensive features for tutoring, AI integration, and payment processing.
