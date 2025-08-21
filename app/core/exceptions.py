class PreplyException(Exception):
    """Base exception for Preply application"""
    pass


class SchedulingError(PreplyException):
    """Exception raised for scheduling-related errors"""
    pass


class BookingError(PreplyException):
    """Exception raised for booking-related errors"""
    pass


class AvailabilityError(PreplyException):
    """Exception raised for availability-related errors"""
    pass


class PaymentError(PreplyException):
    """Exception raised for payment-related errors"""
    pass


class GoogleCalendarError(PreplyException):
    """Exception raised for Google Calendar integration errors"""
    pass


class CalendarError(PreplyException):
    """Exception raised for calendar-related errors"""
    pass


class AIProcessingError(PreplyException):
    """Exception raised for AI processing errors"""
    pass


class FileUploadError(PreplyException):
    """Exception raised for file upload errors"""
    pass


class AuthenticationError(PreplyException):
    """Exception raised for authentication errors"""
    pass


class AuthorizationError(PreplyException):
    """Exception raised for authorization errors"""
    pass


class ValidationError(PreplyException):
    """Exception raised for validation errors"""
    pass


class DatabaseError(PreplyException):
    """Exception raised for database errors"""
    pass


class ExternalServiceError(PreplyException):
    """Exception raised for external service errors"""
    pass


class NotificationError(PreplyException):
    """Exception raised for notification errors"""
    pass


class CreditError(PreplyException):
    """Exception raised for credit-related errors"""
    pass


class SubscriptionError(PreplyException):
    """Exception raised for subscription-related errors"""
    pass


class OAuthError(PreplyException):
    """Exception raised for OAuth-related errors"""
    pass
