# Preply Scheduling System

## Overview

The Preply scheduling system is a comprehensive, enterprise-grade solution for managing tutor availability, student bookings, and calendar integration. It's designed to handle complex scheduling scenarios with proper transaction safety, timezone management, and scalability.

## Architecture

### Core Components

1. **SchedulingService** - Main business logic for availability and booking management
2. **GoogleCalendarService** - Google Calendar integration with OAuth
3. **NotificationService** - Multi-channel notifications (email, SMS, in-app)
4. **Background Tasks** - Automated reminders and maintenance
5. **API Endpoints** - RESTful interface for all scheduling operations

### Data Flow

```
Student Request → API → SchedulingService → Database
                                    ↓
                            GoogleCalendarService
                                    ↓
                            NotificationService
                                    ↓
                            Email/SMS/In-App
```

## Key Features

### 1. Availability Management

#### Recurring Availability
- **RRULE Support**: Full iCalendar RRULE compliance for complex recurring patterns
- **Time-off Blocks**: Blackout periods for tutors
- **Automatic Slot Generation**: Creates bookable slots 8 weeks in advance
- **Conflict Detection**: Prevents double-booking and time conflicts

#### Example RRULE Patterns
```python
# Every Monday and Wednesday 4-7 PM
"FREQ=WEEKLY;BYDAY=MO,WE;BYHOUR=16,17,18"

# Every other week on Tuesday 2-4 PM
"FREQ=WEEKLY;INTERVAL=2;BYDAY=TU;BYHOUR=14,15"

# Monthly on the first Monday
"FREQ=MONTHLY;BYDAY=1MO;BYHOUR=10,11,12"
```

### 2. Booking Flow

#### Slot Holding System
- **10-minute Hold**: Prevents race conditions during booking
- **Transaction Safety**: Database-level locking prevents double-booking
- **Unique Constraints**: `(tutor_id, start_at)` ensures no conflicts

#### Payment Integration
- **Multiple Methods**: Credits, Stripe, subscription-based
- **Payment Gates**: Validates payment before confirming booking
- **Refund Handling**: Automatic refunds for cancellations

### 3. Google Calendar Integration

#### OAuth Flow
1. User authorizes Google Calendar access
2. Store encrypted tokens in database
3. Automatic token refresh handling
4. Calendar event creation/deletion

#### Busy Time Sync
- **Free/Busy API**: Queries Google Calendar for conflicts
- **Real-time Updates**: Background sync every 30 minutes
- **Automatic Slot Closure**: Hides conflicting slots from students

#### Event Management
- **Dual Events**: Creates separate events for tutor and student
- **ICS Fallback**: Email attachments for non-connected users
- **Webhook Support**: Real-time calendar change detection

### 4. Notification System

#### Multi-Channel Delivery
- **Email**: HTML templates with booking details
- **SMS**: Short reminders and confirmations
- **In-App**: Real-time notifications in the platform

#### Automated Reminders
- **24-hour Reminder**: Email + SMS (if opted in)
- **2-hour Reminder**: Final reminder with join link
- **Background Processing**: Hourly reminder checks

## API Endpoints

### Availability Management

#### Create Availability Block
```http
POST /api/v1/scheduling/availability
Content-Type: application/json

{
  "start_at": "2024-01-15T16:00:00Z",
  "end_at": "2024-01-15T19:00:00Z",
  "is_recurring": true,
  "rrule_string": "FREQ=WEEKLY;BYDAY=MO,WE;BYHOUR=16,17,18"
}
```

#### Create Time-off Block
```http
POST /api/v1/scheduling/availability/time-off
Content-Type: application/json

{
  "start_at": "2024-01-20T10:00:00Z",
  "end_at": "2024-01-20T18:00:00Z"
}
```

#### Get Available Slots
```http
GET /api/v1/scheduling/availability/{tutor_id}/slots?start_date=2024-01-15T00:00:00Z&end_date=2024-01-22T23:59:59Z&timezone=America/New_York
```

### Booking Management

#### Hold Slot
```http
POST /api/v1/scheduling/booking/hold
Content-Type: application/json

{
  "slot_id": "uuid-of-slot"
}
```

#### Confirm Booking
```http
POST /api/v1/scheduling/booking/confirm
Content-Type: application/json

{
  "slot_id": "uuid-of-slot",
  "payment_method": "credit",
  "payment_intent_id": null
}
```

#### Get My Bookings
```http
GET /api/v1/scheduling/bookings?status=confirmed
```

#### Cancel Booking
```http
POST /api/v1/scheduling/bookings/{booking_id}/cancel
Content-Type: application/json

{
  "reason": "Schedule conflict"
}
```

#### Reschedule Booking
```http
POST /api/v1/scheduling/bookings/{booking_id}/reschedule
Content-Type: application/json

{
  "new_slot_id": "uuid-of-new-slot",
  "reason": "Better time slot available"
}
```

### Google Calendar Integration

#### Get Auth URL
```http
GET /api/v1/scheduling/calendar/auth-url
```

#### Connect Calendar
```http
POST /api/v1/scheduling/calendar/connect
Content-Type: application/json

{
  "code": "google-oauth-code"
}
```

#### Get Calendars
```http
GET /api/v1/scheduling/calendar/calendars
```

#### Disconnect Calendar
```http
DELETE /api/v1/scheduling/calendar/disconnect
```

## Database Schema

### Core Tables

#### availability_blocks
- `tutor_id`: UUID reference to users
- `start_at`: UTC timestamp
- `end_at`: UTC timestamp
- `is_recurring`: Boolean flag
- `rrule`: iCalendar RRULE string

#### time_off_blocks
- `tutor_id`: UUID reference to users
- `start_at`: UTC timestamp
- `end_at`: UTC timestamp

#### slots
- `tutor_id`: UUID reference to users
- `start_at`: UTC timestamp
- `end_at`: UTC timestamp
- `status`: ENUM (open, held, booked, closed)
- **Unique Index**: `(tutor_id, start_at)` prevents double-booking

#### bookings
- `student_id`: UUID reference to users
- `tutor_id`: UUID reference to users
- `start_at`: UTC timestamp
- `end_at`: UTC timestamp
- `status`: ENUM (pending_payment, confirmed, canceled, completed, refunded)
- `price_cents`: Integer amount in cents
- `payment_intent_id`: Stripe payment intent
- `calendar_event_id_student`: Google Calendar event ID
- `calendar_event_id_tutor`: Google Calendar event ID
- `join_link`: Meeting URL
- `slot_id`: UUID reference to slots

#### google_oauth_accounts
- `user_id`: UUID reference to users
- `access_token`: Encrypted access token
- `refresh_token`: Encrypted refresh token
- `expiry`: Token expiry timestamp
- `scopes`: JSON array of granted scopes

## Background Tasks

### Automated Processes

#### Booking Reminders
- **Frequency**: Every hour
- **24h Reminder**: Email + SMS + In-app notification
- **2h Reminder**: Final reminder with join link

#### Expired Hold Cleanup
- **Frequency**: Every 5 minutes
- **Action**: Release slots held for >10 minutes
- **Purpose**: Prevent slot hoarding

#### Future Slot Generation
- **Frequency**: Daily at 2 AM
- **Action**: Generate slots for next 8 weeks
- **Trigger**: Recurring availability blocks

#### Google Calendar Sync
- **Frequency**: Every 30 minutes
- **Action**: Update slot availability based on busy times
- **Purpose**: Real-time calendar integration

#### No-show Processing
- **Frequency**: Every 15 minutes
- **Action**: Mark past bookings as completed
- **Purpose**: Automatic session completion

#### Old Slot Cleanup
- **Frequency**: Daily at 3 AM
- **Action**: Soft delete slots older than 3 months
- **Purpose**: Database maintenance

## Security Considerations

### Data Protection
- **Encrypted Tokens**: OAuth tokens encrypted at rest
- **Soft Deletes**: Data retention for audit purposes
- **Access Control**: Role-based API access

### Transaction Safety
- **Database Locks**: `SELECT ... FOR UPDATE` prevents race conditions
- **Unique Constraints**: Database-level double-booking prevention
- **Atomic Operations**: All booking operations in transactions

### Timezone Handling
- **UTC Storage**: All timestamps stored in UTC
- **Client Conversion**: Timezone conversion in application layer
- **DST Support**: Automatic daylight saving time handling

## Performance Optimizations

### Database Indexing
- **Primary Keys**: UUID with gen_random_uuid()
- **Foreign Keys**: Indexed for join performance
- **Time Queries**: Indexes on start_at and end_at
- **Status Queries**: Indexes on booking and slot status

### Caching Strategy
- **Slot Availability**: Cache frequently queried slots
- **User Profiles**: Cache tutor and student profiles
- **Calendar Data**: Cache Google Calendar busy times

### Query Optimization
- **Bulk Operations**: Batch slot generation and cleanup
- **Pagination**: Limit result sets for large queries
- **Selective Loading**: Load only required relationships

## Error Handling

### Custom Exceptions
- `SchedulingError`: Availability and slot management errors
- `BookingError`: Booking flow and payment errors
- `GoogleCalendarError`: Calendar integration errors
- `PaymentError`: Payment processing errors

### Graceful Degradation
- **Calendar Sync**: Failures don't block booking flow
- **Notification Delivery**: Email failures don't prevent booking
- **External Services**: Timeout handling for third-party APIs

## Monitoring and Logging

### Key Metrics
- **Booking Success Rate**: Percentage of successful bookings
- **Slot Utilization**: How many slots are booked vs. available
- **Calendar Sync Success**: Google Calendar integration health
- **Notification Delivery**: Email/SMS delivery rates

### Logging Strategy
- **Structured Logging**: JSON format for easy parsing
- **Error Tracking**: Detailed error context for debugging
- **Performance Monitoring**: Query execution times and bottlenecks

## Deployment Considerations

### Environment Variables
```bash
# Google Calendar
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=https://your-domain.com/auth/google/callback

# Email Service
RESEND_API_KEY=your-resend-api-key

# SMS Service
TWILIO_ACCOUNT_SID=your-twilio-sid
TWILIO_AUTH_TOKEN=your-twilio-token

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/preply

# Redis (for caching and task queue)
REDIS_URL=redis://localhost:6379
```

### Scaling Strategy
- **Horizontal Scaling**: Multiple API instances behind load balancer
- **Database Sharding**: Shard by user_id for large scale
- **Task Queue**: Celery/Redis for background tasks
- **CDN**: Static assets and ICS files

## Testing Strategy

### Unit Tests
- **Service Layer**: Test business logic in isolation
- **Model Validation**: Test data integrity constraints
- **Exception Handling**: Test error scenarios

### Integration Tests
- **API Endpoints**: Test complete request/response cycles
- **Database Operations**: Test transaction safety
- **External Services**: Mock Google Calendar and payment APIs

### End-to-End Tests
- **Booking Flow**: Complete booking from availability to confirmation
- **Calendar Integration**: OAuth flow and event creation
- **Notification Delivery**: Email and SMS sending

## Future Enhancements

### Planned Features
- **Video Integration**: Zoom/Google Meet automatic link generation
- **Group Sessions**: Multiple students in one session
- **Recurring Bookings**: Automatic weekly/monthly bookings
- **Waitlist System**: Queue for popular time slots
- **Analytics Dashboard**: Booking patterns and tutor performance

### Technical Improvements
- **WebSocket Support**: Real-time availability updates
- **Mobile Push Notifications**: Native app notifications
- **Advanced Calendar Sync**: Two-way sync with external calendars
- **AI-Powered Scheduling**: Smart slot recommendations

This scheduling system provides a robust, scalable foundation for managing complex tutoring schedules with enterprise-grade reliability and performance.
