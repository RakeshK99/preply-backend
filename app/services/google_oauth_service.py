from typing import Dict, Any
import aiohttp
from urllib.parse import urlencode

from app.core.config import settings
from app.core.exceptions import OAuthError


class GoogleOAuthService:
    """Service for Google OAuth authentication"""
    
    def __init__(self):
        self.client_id = settings.GOOGLE_CLIENT_ID
        self.client_secret = settings.GOOGLE_CLIENT_SECRET
        self.redirect_uri = settings.GOOGLE_REDIRECT_URI
        self.scope = "https://www.googleapis.com/auth/calendar"
    
    def get_authorization_url(self, state: str) -> str:
        """Generate Google OAuth authorization URL"""
        try:
            params = {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "scope": self.scope,
                "response_type": "code",
                "access_type": "offline",
                "prompt": "consent",
                "state": state
            }
            
            auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
            return auth_url
            
        except Exception as e:
            raise OAuthError(f"Failed to generate authorization URL: {str(e)}")
    
    async def exchange_code_for_tokens(self, code: str) -> Dict[str, Any]:
        """Exchange authorization code for access and refresh tokens"""
        try:
            token_url = "https://oauth2.googleapis.com/token"
            
            data = {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(token_url, data=data) as response:
                    if response.status != 200:
                        error_data = await response.json()
                        raise OAuthError(f"Token exchange failed: {error_data}")
                    
                    token_data = await response.json()
                    
                    return {
                        "access_token": token_data.get("access_token"),
                        "refresh_token": token_data.get("refresh_token"),
                        "expires_in": token_data.get("expires_in"),
                        "token_type": token_data.get("token_type")
                    }
                    
        except Exception as e:
            raise OAuthError(f"Failed to exchange code for tokens: {str(e)}")
    
    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh access token using refresh token"""
        try:
            token_url = "https://oauth2.googleapis.com/token"
            
            data = {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(token_url, data=data) as response:
                    if response.status != 200:
                        error_data = await response.json()
                        raise OAuthError(f"Token refresh failed: {error_data}")
                    
                    token_data = await response.json()
                    
                    return {
                        "access_token": token_data.get("access_token"),
                        "expires_in": token_data.get("expires_in"),
                        "token_type": token_data.get("token_type")
                    }
                    
        except Exception as e:
            raise OAuthError(f"Failed to refresh access token: {str(e)}")
    
    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """Get user information from Google"""
        try:
            userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
            
            headers = {
                "Authorization": f"Bearer {access_token}"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(userinfo_url, headers=headers) as response:
                    if response.status != 200:
                        error_data = await response.json()
                        raise OAuthError(f"Failed to get user info: {error_data}")
                    
                    user_data = await response.json()
                    
                    return {
                        "id": user_data.get("id"),
                        "email": user_data.get("email"),
                        "name": user_data.get("name"),
                        "given_name": user_data.get("given_name"),
                        "family_name": user_data.get("family_name"),
                        "picture": user_data.get("picture")
                    }
                    
        except Exception as e:
            raise OAuthError(f"Failed to get user info: {str(e)}")
    
    async def revoke_token(self, token: str) -> bool:
        """Revoke access token"""
        try:
            revoke_url = "https://oauth2.googleapis.com/revoke"
            
            data = {
                "token": token
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(revoke_url, data=data) as response:
                    return response.status == 200
                    
        except Exception as e:
            raise OAuthError(f"Failed to revoke token: {str(e)}")
