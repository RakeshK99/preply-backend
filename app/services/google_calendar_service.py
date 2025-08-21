from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import httpx
import json
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import base64
import os

from app.core.config import settings
from app.core.exceptions import GoogleCalendarError


class GoogleCalendarService:
    """Google Calendar integration service for availability and event management"""
    
    def __init__(self):
        self.client_id = settings.GOOGLE_CLIENT_ID
        self.client_secret = settings.GOOGLE_CLIENT_SECRET
        self.redirect_uri = settings.GOOGLE_REDIRECT_URI
    
    def get_authorization_url(self, state: str = None) -> str:
        """Generate Google OAuth authorization URL"""
        from google_auth_oauthlib.flow import Flow
        
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [self.redirect_uri]
                }
            },
            scopes=[
                "https://www.googleapis.com/auth/calendar.events",
                "https://www.googleapis.com/auth/calendar.readonly",
                "openid",
                "email",
                "profile"
            ]
        )
        
        flow.redirect_uri = self.redirect_uri
        
        if state:
            flow.state = state
        
        return flow.authorization_url()[0]
    
    async def exchange_code_for_tokens(self, code: str) -> Dict[str, Any]:
        """Exchange authorization code for access and refresh tokens"""
        from google_auth_oauthlib.flow import Flow
        
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [self.redirect_uri]
                }
            },
            scopes=[
                "https://www.googleapis.com/auth/calendar.events",
                "https://www.googleapis.com/auth/calendar.readonly",
                "openid",
                "email",
                "profile"
            ]
        )
        
        flow.redirect_uri = self.redirect_uri
        
        try:
            flow.fetch_token(code=code)
            credentials = flow.credentials
            
            return {
                "access_token": credentials.token,
                "refresh_token": credentials.refresh_token,
                "expiry": credentials.expiry.isoformat() if credentials.expiry else None,
                "scopes": credentials.scopes
            }
        except Exception as e:
            raise GoogleCalendarError(f"Failed to exchange code for tokens: {str(e)}")
    
    def _decrypt_token(self, encrypted_token: str) -> str:
        """Decrypt stored token (implement with your encryption method)"""
        # In production, use proper encryption/decryption
        # For now, we'll assume tokens are stored encrypted
        return encrypted_token
    
    def _encrypt_token(self, token: str) -> str:
        """Encrypt token for storage (implement with your encryption method)"""
        # In production, use proper encryption
        # For now, we'll assume tokens are stored encrypted
        return token
    
    def _get_credentials(self, access_token: str, refresh_token: str = None, expiry: str = None) -> Credentials:
        """Create Google credentials object from stored tokens"""
        expiry_dt = None
        if expiry:
            expiry_dt = datetime.fromisoformat(expiry.replace('Z', '+00:00'))
        
        credentials = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=[
                "https://www.googleapis.com/auth/calendar.events",
                "https://www.googleapis.com/auth/calendar.readonly"
            ],
            expiry=expiry_dt
        )
        
        return credentials
    
    async def get_busy_times(
        self,
        access_token: str,
        start_date: datetime,
        end_date: datetime,
        calendar_id: str = "primary"
    ) -> List[Dict[str, Any]]:
        """Get busy times from Google Calendar using Free/Busy API"""
        try:
            credentials = self._get_credentials(access_token)
            
            # Refresh token if needed
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            
            service = build('calendar', 'v3', credentials=credentials)
            
            # Prepare request body for free/busy query
            body = {
                'timeMin': start_date.isoformat() + 'Z',
                'timeMax': end_date.isoformat() + 'Z',
                'items': [{'id': calendar_id}]
            }
            
            # Call the Free/Busy API
            events_result = service.freebusy().query(body=body).execute()
            
            busy_times = []
            calendars = events_result.get('calendars', {})
            
            if calendar_id in calendars:
                busy_periods = calendars[calendar_id].get('busy', [])
                for period in busy_periods:
                    busy_times.append({
                        'start': period['start'],
                        'end': period['end']
                    })
            
            return busy_times
            
        except HttpError as error:
            raise GoogleCalendarError(f"Google Calendar API error: {error}")
        except Exception as e:
            raise GoogleCalendarError(f"Failed to get busy times: {str(e)}")
    
    async def create_event(
        self,
        access_token: str,
        summary: str,
        description: str,
        start_time: datetime,
        end_time: datetime,
        attendee_email: Optional[str] = None,
        location: Optional[str] = None,
        calendar_id: str = "primary"
    ) -> str:
        """Create Google Calendar event"""
        try:
            credentials = self._get_credentials(access_token)
            
            # Refresh token if needed
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            
            service = build('calendar', 'v3', credentials=credentials)
            
            # Prepare event body
            event = {
                'summary': summary,
                'description': description,
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': 'UTC',
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': 'UTC',
                },
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'email', 'minutes': 24 * 60},  # 24 hours
                        {'method': 'popup', 'minutes': 30},  # 30 minutes
                    ],
                },
            }
            
            # Add attendee if provided
            if attendee_email:
                event['attendees'] = [{'email': attendee_email}]
            
            # Add location if provided
            if location:
                event['location'] = location
            
            # Create the event
            event_result = service.events().insert(
                calendarId=calendar_id,
                body=event,
                sendUpdates='all'  # Send email notifications to attendees
            ).execute()
            
            return event_result['id']
            
        except HttpError as error:
            raise GoogleCalendarError(f"Google Calendar API error: {error}")
        except Exception as e:
            raise GoogleCalendarError(f"Failed to create event: {str(e)}")
    
    async def update_event(
        self,
        access_token: str,
        event_id: str,
        summary: Optional[str] = None,
        description: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        calendar_id: str = "primary"
    ) -> Dict[str, Any]:
        """Update existing Google Calendar event"""
        try:
            credentials = self._get_credentials(access_token)
            
            # Refresh token if needed
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            
            service = build('calendar', 'v3', credentials=credentials)
            
            # Get existing event
            event = service.events().get(
                calendarId=calendar_id,
                eventId=event_id
            ).execute()
            
            # Update fields if provided
            if summary:
                event['summary'] = summary
            if description:
                event['description'] = description
            if start_time:
                event['start']['dateTime'] = start_time.isoformat()
            if end_time:
                event['end']['dateTime'] = end_time.isoformat()
            
            # Update the event
            updated_event = service.events().update(
                calendarId=calendar_id,
                eventId=event_id,
                body=event,
                sendUpdates='all'
            ).execute()
            
            return updated_event
            
        except HttpError as error:
            raise GoogleCalendarError(f"Google Calendar API error: {error}")
        except Exception as e:
            raise GoogleCalendarError(f"Failed to update event: {str(e)}")
    
    async def delete_event(
        self,
        access_token: str,
        event_id: str,
        calendar_id: str = "primary"
    ) -> bool:
        """Delete Google Calendar event"""
        try:
            credentials = self._get_credentials(access_token)
            
            # Refresh token if needed
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            
            service = build('calendar', 'v3', credentials=credentials)
            
            # Delete the event
            service.events().delete(
                calendarId=calendar_id,
                eventId=event_id,
                sendUpdates='all'
            ).execute()
            
            return True
            
        except HttpError as error:
            if error.resp.status == 404:
                # Event already deleted or doesn't exist
                return True
            raise GoogleCalendarError(f"Google Calendar API error: {error}")
        except Exception as e:
            raise GoogleCalendarError(f"Failed to delete event: {str(e)}")
    
    async def get_calendar_list(self, access_token: str) -> List[Dict[str, Any]]:
        """Get list of user's calendars"""
        try:
            credentials = self._get_credentials(access_token)
            
            # Refresh token if needed
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            
            service = build('calendar', 'v3', credentials=credentials)
            
            # Get calendar list
            calendar_list = service.calendarList().list().execute()
            
            calendars = []
            for calendar in calendar_list.get('items', []):
                calendars.append({
                    'id': calendar['id'],
                    'summary': calendar['summary'],
                    'primary': calendar.get('primary', False),
                    'accessRole': calendar.get('accessRole', 'none')
                })
            
            return calendars
            
        except HttpError as error:
            raise GoogleCalendarError(f"Google Calendar API error: {error}")
        except Exception as e:
            raise GoogleCalendarError(f"Failed to get calendar list: {str(e)}")
    
    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh access token using refresh token"""
        try:
            credentials = Credentials(
                None,  # No access token initially
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.client_id,
                client_secret=self.client_secret
            )
            
            # Refresh the token
            credentials.refresh(Request())
            
            return {
                "access_token": credentials.token,
                "expiry": credentials.expiry.isoformat() if credentials.expiry else None
            }
            
        except Exception as e:
            raise GoogleCalendarError(f"Failed to refresh access token: {str(e)}")
    
    def generate_ics_file(
        self,
        summary: str,
        description: str,
        start_time: datetime,
        end_time: datetime,
        location: Optional[str] = None,
        attendee_email: Optional[str] = None
    ) -> str:
        """Generate ICS file content for calendar event"""
        ics_content = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Preply//Tutoring Session//EN",
            "BEGIN:VEVENT",
            f"UID:{start_time.strftime('%Y%m%dT%H%M%SZ')}@preply.com",
            f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
            f"DTSTART:{start_time.strftime('%Y%m%dT%H%M%SZ')}",
            f"DTEND:{end_time.strftime('%Y%m%dT%H%M%SZ')}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{description.replace(chr(10), '\\n').replace(chr(13), '\\n')}",
        ]
        
        if location:
            ics_content.append(f"LOCATION:{location}")
        
        if attendee_email:
            ics_content.append(f"ATTENDEE:mailto:{attendee_email}")
        
        ics_content.extend([
            "END:VEVENT",
            "END:VCALENDAR"
        ])
        
        return "\r\n".join(ics_content)
    
    async def setup_webhook(
        self,
        access_token: str,
        webhook_url: str,
        calendar_id: str = "primary"
    ) -> Dict[str, Any]:
        """Set up Google Calendar webhook for real-time updates"""
        try:
            credentials = self._get_credentials(access_token)
            
            # Refresh token if needed
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            
            service = build('calendar', 'v3', credentials=credentials)
            
            # Create webhook channel
            channel = {
                'id': f"preply-{calendar_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                'type': 'web_hook',
                'address': webhook_url,
                'expiration': int((datetime.now() + timedelta(days=7)).timestamp() * 1000)  # 7 days
            }
            
            # Set up the webhook
            result = service.events().watch(
                calendarId=calendar_id,
                body=channel
            ).execute()
            
            return {
                'channel_id': result['id'],
                'resource_id': result['resourceId'],
                'expiration': result['expiration']
            }
            
        except HttpError as error:
            raise GoogleCalendarError(f"Google Calendar API error: {error}")
        except Exception as e:
            raise GoogleCalendarError(f"Failed to setup webhook: {str(e)}")
    
    async def stop_webhook(
        self,
        access_token: str,
        channel_id: str,
        resource_id: str
    ) -> bool:
        """Stop Google Calendar webhook"""
        try:
            credentials = self._get_credentials(access_token)
            
            # Refresh token if needed
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            
            service = build('calendar', 'v3', credentials=credentials)
            
            # Stop the webhook
            service.channels().stop(body={
                'id': channel_id,
                'resourceId': resource_id
            }).execute()
            
            return True
            
        except HttpError as error:
            raise GoogleCalendarError(f"Google Calendar API error: {error}")
        except Exception as e:
            raise GoogleCalendarError(f"Failed to stop webhook: {str(e)}")
