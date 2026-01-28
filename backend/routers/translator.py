from fastapi import APIRouter, Depends, HTTPException
from utils.database import get_db
from utils.security import get_current_user
from pydantic import BaseModel
from azure.ai.translation.text.models import InputTextItem
from models.User import User
import os
from azure.ai.translation.text import TextTranslationClient, TranslatorCredential
import uuid
import requests
from requests.exceptions import RequestException, ProxyError, Timeout
import urllib3

# Disable SSL warnings when using verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

key = os.getenv("AZURE_TRANSLATOR_KEY")
endpoint = os.getenv("AZURE_TRANSLATOR_ENDPOINT")
region = os.getenv("AZURE_TRANSLATOR_REGION")

router = APIRouter(
    prefix="/translator",
    tags=["translator"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


class DetectedLanguage(BaseModel):
    language: str
    score: float


class Translation(BaseModel):
    text: str
    to: str


class TranslationResponse(BaseModel):
    detected_language: DetectedLanguage
    translations: list[Translation]


class TranslationRequest(BaseModel):
    text: str
    target_language: str


@router.post("/translate")
async def translate(
    translation_request: TranslationRequest,
    current_user: User = Depends(get_current_user),
) -> TranslationResponse:
    # Ensure endpoint ends with / for proper URL construction
    endpoint_url = endpoint if endpoint.endswith('/') else f"{endpoint}/"
    url = f"{endpoint_url}translate"
    params = {
        'api-version': '3.0',
        'to': [translation_request.target_language]
    }

    headers = {
        'Ocp-Apim-Subscription-Key': key,
        'Ocp-Apim-Subscription-Region': region,
        'Content-type': 'application/json',
        'X-ClientTraceId': str(uuid.uuid4())
    }
    body = [{
        'text': translation_request.text
    }]

    # Check for proxy configuration
    proxy_url = os.getenv('HTTP_PROXY') or os.getenv('HTTPS_PROXY') or os.getenv('ASW_PROXY_URL')
    
    proxies = None
    if proxy_url:
        proxies = {
            'http': proxy_url,
            'https': proxy_url
        }
        print(f"Using proxy: {proxy_url}")
    else:
        print("No proxy configured")
    
    # Configure timeout (30 seconds for connect, 60 seconds for read)
    timeout = (30, 60)
    
    try:
        print(f"Sending request to {url} with params {params}, headers {headers}, and body {body}")
        
        # Use requests library which handles corporate proxies better
        response = requests.post(
            url,
            params=params,
            headers=headers,
            json=body,
            proxies=proxies,
            verify=False,  # Disable SSL verification
            timeout=timeout
        )
        
        print(f"Request successful! Status: {response.status_code}")
        response.raise_for_status()
        
    except Timeout as e:
        print(f"Request timeout: {e}")
        raise HTTPException(status_code=504, detail="Translation service timeout")
    except ProxyError as e:
        print(f"Proxy error: {e}")
        raise HTTPException(status_code=502, detail=f"Proxy error: {str(e)}")
    except RequestException as e:
        print(f"HTTP Request failed: {e}")
        raise HTTPException(status_code=500, detail=f"Translation service error: {str(e)}")
    
    response_data = response.json()

    if isinstance(response_data, list) and len(response_data) > 0:
        first_result = response_data[0]
        return TranslationResponse(
            detected_language=DetectedLanguage(
                language=first_result['detectedLanguage']['language'],
                score=first_result['detectedLanguage']['score'],
            ),
            translations=[
                Translation(
                    text=translation['text'],
                    to=translation['to'],
                )
                for translation in first_result['translations']
            ],
        )
    else:
        # Handle error or empty response
        print(f"Unexpected response format: {response_data}")
        raise HTTPException(status_code=400, detail="Translation failed or unexpected response")