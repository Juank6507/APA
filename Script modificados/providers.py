import sys
import os
import time
import json
import logging
from abc import ABC, abstractmethod
from typing import Optional
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config.settings import settings

import requests

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)


class ModelProvider(ABC):
    nombre: str
    prioridad: int
    
    @abstractmethod
    def is_available(self) -> bool:
        pass
    
    @abstractmethod
    def call(
        self,
        model_id: str,
        messages: list[dict],
        max_tokens: int = 2000,
        temperature: float = 0.1
    ) -> dict:
        pass
    
    @abstractmethod
    def get_models(self) -> list[dict]:
        pass


class OpenRouterProvider(ModelProvider):
    nombre = "openrouter"
    prioridad = 1
    _cache = {"available": None, "timestamp": None}
    
    def is_available(self) -> bool:
        if not settings.openrouter_api_key:
            return False
        
        now = time.time()
        if self._cache["available"] is not None and self._cache["timestamp"] is not None:
            if now - self._cache["timestamp"] < 300:
                return self._cache["available"]
        
        try:
            response = requests.get(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
                timeout=5
            )
            result = response.status_code == 200
        except:
            result = False
        
        self._cache["available"] = result
        self._cache["timestamp"] = now
        return result
    
    def call(self, model_id: str, messages: list[dict], max_tokens: int = 2000, temperature: float = 0.1) -> dict:
        try:
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:8080",
                "X-Title": "APA-Agent"
            }
            payload = {
                "model": model_id,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            
            if response.status_code == 429:
                return {
                    "content": "",
                    "model_used": model_id,
                    "provider": self.nombre,
                    "success": False,
                    "error": "rate_limit"
                }
            
            if response.status_code == 200:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                return {
                    "content": content,
                    "model_used": model_id,
                    "provider": self.nombre,
                    "success": True,
                    "error": None
                }
            
            return {
                "content": "",
                "model_used": model_id,
                "provider": self.nombre,
                "success": False,
                "error": f"HTTP {response.status_code}"
            }
        except Exception as e:
            return {
                "content": "",
                "model_used": model_id,
                "provider": self.nombre,
                "success": False,
                "error": str(e)
            }
    
    def get_models(self) -> list[dict]:
        try:
            from core.router import get_all_available_models as get_or_models
            return get_or_models()
        except:
            return []


class AnthropicProvider(ModelProvider):
    nombre = "anthropic"
    prioridad = 2
    
    ANTHROPIC_MODELS = [
        {
            "id": "claude-opus-4-5",
            "name": "Claude Opus 4.5",
            "context_length": 200000,
            "capabilities": ["long_context","coding","instruction"],
            "quality_score": 99,
            "is_free_tier": False,
            "provider": "anthropic"
        },
        {
            "id": "claude-sonnet-4-5",
            "name": "Claude Sonnet 4.5",
            "context_length": 200000,
            "capabilities": ["long_context","coding","instruction"],
            "quality_score": 96,
            "is_free_tier": False,
            "provider": "anthropic"
        },
        {
            "id": "claude-haiku-4-5-20251001",
            "name": "Claude Haiku 4.5",
            "context_length": 200000,
            "capabilities": ["long_context","instruction"],
            "quality_score": 88,
            "is_free_tier": False,
            "provider": "anthropic"
        }
    ]
    
    def is_available(self) -> bool:
        return bool(settings.anthropic_api_key)
    
    def call(self, model_id: str, messages: list[dict], max_tokens: int = 2000, temperature: float = 0.1) -> dict:
        try:
            url = "https://api.anthropic.com/v1/messages"
            headers = {
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }
            
            anthropic_messages = [
                m for m in messages
                if m["role"] != "system"
            ]
            system_content = next(
                (m["content"] for m in messages
                 if m["role"] == "system"), None
            )
            
            payload = {
                "model": model_id,
                "max_tokens": max_tokens,
                "messages": anthropic_messages
            }
            if system_content:
                payload["system"] = system_content
            
            logger.info(f"Calling Anthropic API with model: {model_id}")
            response = requests.post(
                url, headers=headers,
                json=payload, timeout=120
            )
            
            logger.info(f"Anthropic response status: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"Anthropic error: {response.text}")
                error_text = response.text.lower()
                if "credit balance" in error_text or "billing" in error_text or "upgrade" in error_text:
                    return {
                        "content": "",
                        "model_used": model_id,
                        "provider": "anthropic",
                        "success": False,
                        "error": "provider_unavailable"
                    }
            
            response.raise_for_status()
            data = response.json()
            content = data["content"][0]["text"]
            
            return {
                "content": content,
                "model_used": model_id,
                "provider": "anthropic",
                "success": True,
                "error": None
            }
        except Exception as e:
            logger.error(f"AnthropicProvider.call error: {str(e)}")
            error_str = str(e).lower()
            if "credit" in error_str or "billing" in error_str or "upgrade" in error_str:
                return {
                    "content": "",
                    "model_used": model_id,
                    "provider": "anthropic",
                    "success": False,
                    "error": "provider_unavailable"
                }
            return {
                "content": "",
                "model_used": model_id,
                "provider": "anthropic",
                "success": False,
                "error": str(e)
            }
    
    def get_models(self) -> list[dict]:
        return self.ANTHROPIC_MODELS.copy()


class OpenAIProvider(ModelProvider):
    nombre = "openai"
    prioridad = 3
    
    OPENAI_MODELS = [
        {
            "id": "gpt-4o",
            "name": "GPT-4o",
            "context_length": 128000,
            "capabilities": ["long_context","coding","instruction"],
            "quality_score": 95,
            "is_free_tier": False,
            "provider": "openai"
        },
        {
            "id": "gpt-4o-mini",
            "name": "GPT-4o Mini",
            "context_length": 128000,
            "capabilities": ["long_context","instruction"],
            "quality_score": 82,
            "is_free_tier": False,
            "provider": "openai"
        }
    ]
    
    def is_available(self) -> bool:
        return bool(settings.openai_api_key)
    
    def call(self, model_id: str, messages: list[dict], max_tokens: int = 2000, temperature: float = 0.1) -> dict:
        try:
            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model_id,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            
            if response.status_code == 200:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                return {
                    "content": content,
                    "model_used": model_id,
                    "provider": self.nombre,
                    "success": True,
                    "error": None
                }
            
            error_text = response.text.lower() if hasattr(response, 'text') else ""
            if "insufficient_quota" in error_text or "billing" in error_text:
                return {
                    "content": "",
                    "model_used": model_id,
                    "provider": self.nombre,
                    "success": False,
                    "error": "provider_unavailable"
                }
            
            return {
                "content": "",
                "model_used": model_id,
                "provider": self.nombre,
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text}"
            }
        except Exception as e:
            error_str = str(e).lower()
            if "insufficient_quota" in error_str or "billing" in error_str:
                return {
                    "content": "",
                    "model_used": model_id,
                    "provider": self.nombre,
                    "success": False,
                    "error": "provider_unavailable"
                }
            return {
                "content": "",
                "model_used": model_id,
                "provider": self.nombre,
                "success": False,
                "error": str(e)
            }
    
    def get_models(self) -> list[dict]:
        return self.OPENAI_MODELS.copy()


class OllamaProvider(ModelProvider):
    nombre = "ollama"
    prioridad = 4
    _cache = {"available": None, "timestamp": None}
    
    def is_available(self) -> bool:
        now = time.time()
        if self._cache["available"] is not None and self._cache["timestamp"] is not None:
            if now - self._cache["timestamp"] < 120:
                return self._cache["available"]
        
        try:
            response = requests.get(
                f"{settings.ollama_base_url}/api/tags",
                timeout=3
            )
            result = response.status_code == 200
        except:
            result = False
        
        self._cache["available"] = result
        self._cache["timestamp"] = now
        return result
    
    def call(self, model_id: str, messages: list[dict], max_tokens: int = 2000, temperature: float = 0.1) -> dict:
        try:
            url = f"{settings.ollama_base_url}/api/chat"
            payload = {
                "model": model_id,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens
                }
            }
            
            response = requests.post(url, json=payload, timeout=120)
            
            if response.status_code == 200:
                data = response.json()
                content = data["message"]["content"]
                return {
                    "content": content,
                    "model_used": model_id,
                    "provider": self.nombre,
                    "success": True,
                    "error": None
                }
            
            return {
                "content": "",
                "model_used": model_id,
                "provider": self.nombre,
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text}"
            }
        except Exception as e:
            return {
                "content": "",
                "model_used": model_id,
                "provider": self.nombre,
                "success": False,
                "error": str(e)
            }
    
    def get_models(self) -> list[dict]:
        try:
            response = requests.get(
                f"{settings.ollama_base_url}/api/tags",
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                models = []
                for model in data.get("models", []):
                    models.append({
                        "id": model["name"],
                        "name": model["name"],
                        "context_length": 8192,
                        "capabilities": ["general"],
                        "quality_score": 70,
                        "is_free_tier": True,
                        "provider": self.nombre
                    })
                return models
        except:
            pass
        return []


class GroqProvider(ModelProvider):
    nombre = "groq"
    prioridad = 5
    _availability_cache = {"available": None, "timestamp": None}
    
    GROQ_MODELS = [
        {
            "id": "llama-3.1-70b-versatile",
            "name": "Llama 3.1 70B (Groq)",
            "context_length": 131072,
            "capabilities": ["long_context","instruction","coding"],
            "quality_score": 86,
            "is_free_tier": True,
            "provider": "groq"
        },
        {
            "id": "llama-3.1-8b-instant",
            "name": "Llama 3.1 8B Instant (Groq)",
            "context_length": 131072,
            "capabilities": ["long_context","instruction"],
            "quality_score": 72,
            "is_free_tier": True,
            "provider": "groq"
        },
        {
            "id": "mixtral-8x7b-32768",
            "name": "Mixtral 8x7B (Groq)",
            "context_length": 32768,
            "capabilities": ["long_context","instruction","coding"],
            "quality_score": 78,
            "is_free_tier": True,
            "provider": "groq"
        },
        {
            "id": "gemma2-9b-it",
            "name": "Gemma2 9B (Groq)",
            "context_length": 8192,
            "capabilities": ["instruction"],
            "quality_score": 65,
            "is_free_tier": True,
            "provider": "groq"
        },
        {
            "id": "llama-3.3-70b-versatile",
            "name": "Llama 3.3 70B (Groq)",
            "context_length": 131072,
            "capabilities": ["long_context","instruction","coding"],
            "quality_score": 88,
            "is_free_tier": True,
            "provider": "groq"
        }
    ]
    
    def is_available(self) -> bool:
        if not settings.groq_api_key:
            return False
        
        now = time.time()
        if self._availability_cache["available"] is not None and self._availability_cache["timestamp"] is not None:
            if now - self._availability_cache["timestamp"] < 300:
                return self._availability_cache["available"]
        
        result = True
        self._availability_cache["available"] = result
        self._availability_cache["timestamp"] = now
        return result
    
    def call(self, model_id: str, messages: list[dict], max_tokens: int = 2000, temperature: float = 0.1) -> dict:
        try:
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model_id,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }
            
            start_time = time.time()
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            elapsed_ms = (time.time() - start_time) * 1000
            
            if response.status_code == 429:
                logger.warning(f"Groq rate limit on model {model_id}")
                return {
                    "content": "",
                    "model_used": model_id,
                    "provider": self.nombre,
                    "success": False,
                    "error": "rate_limit"
                }
            
            if response.status_code == 200:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                logger.info(f"Groq response in {elapsed_ms:.0f}ms for model {model_id}")
                return {
                    "content": content,
                    "model_used": model_id,
                    "provider": self.nombre,
                    "success": True,
                    "error": None
                }
            
            return {
                "content": "",
                "model_used": model_id,
                "provider": self.nombre,
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text}"
            }
        except Exception as e:
            logger.error(f"GroqProvider.call error: {str(e)}")
            return {
                "content": "",
                "model_used": model_id,
                "provider": self.nombre,
                "success": False,
                "error": str(e)
            }
    
    def get_models(self) -> list[dict]:
        return self.GROQ_MODELS.copy()


class GitHubModelsProvider(ModelProvider):
    nombre = "github"
    prioridad = 6
    _availability_cache = {"available": None, "timestamp": None}
    
    GITHUB_MODELS = [
        {
            "id": "gpt-4o",
            "name": "GPT-4o (GitHub)",
            "context_length": 128000,
            "capabilities": ["long_context","instruction","coding"],
            "quality_score": 95,
            "is_free_tier": True,
            "provider": "github"
        },
        {
            "id": "gpt-4o-mini",
            "name": "GPT-4o Mini (GitHub)",
            "context_length": 128000,
            "capabilities": ["long_context","instruction"],
            "quality_score": 82,
            "is_free_tier": True,
            "provider": "github"
        },
        {
            "id": "Meta-Llama-3.1-405B-Instruct",
            "name": "Llama 3.1 405B (GitHub)",
            "context_length": 131072,
            "capabilities": ["long_context","instruction","coding"],
            "quality_score": 92,
            "is_free_tier": True,
            "provider": "github"
        },
        {
            "id": "Meta-Llama-3.1-70B-Instruct",
            "name": "Llama 3.1 70B (GitHub)",
            "context_length": 131072,
            "capabilities": ["long_context","instruction","coding"],
            "quality_score": 85,
            "is_free_tier": True,
            "provider": "github"
        },
        {
            "id": "Mistral-large",
            "name": "Mistral Large (GitHub)",
            "context_length": 131072,
            "capabilities": ["long_context","instruction","coding"],
            "quality_score": 88,
            "is_free_tier": True,
            "provider": "github"
        },
        {
            "id": "Phi-3-medium-128k-instruct",
            "name": "Phi-3 Medium (GitHub)",
            "context_length": 128000,
            "capabilities": ["long_context","instruction"],
            "quality_score": 75,
            "is_free_tier": True,
            "provider": "github"
        }
    ]
    
    def is_available(self) -> bool:
        if not settings.github_token:
            return False
        
        now = time.time()
        if self._availability_cache["available"] is not None and self._availability_cache["timestamp"] is not None:
            if now - self._availability_cache["timestamp"] < 300:
                return self._availability_cache["available"]
        
        result = True
        self._availability_cache["available"] = result
        self._availability_cache["timestamp"] = now
        return result
    
    def call(self, model_id: str, messages: list[dict], max_tokens: int = 2000, temperature: float = 0.1) -> dict:
        try:
            url = "https://models.inference.ai.azure.com/chat/completions"
            headers = {
                "Authorization": f"Bearer {settings.github_token}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model_id,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            
            if response.status_code == 429:
                logger.warning(f"GitHub Models rate limit on model {model_id}")
                return {
                    "content": "",
                    "model_used": model_id,
                    "provider": self.nombre,
                    "success": False,
                    "error": "rate_limit"
                }
            
            if response.status_code == 200:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                return {
                    "content": content,
                    "model_used": model_id,
                    "provider": self.nombre,
                    "success": True,
                    "error": None
                }
            
            return {
                "content": "",
                "model_used": model_id,
                "provider": self.nombre,
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text}"
            }
        except Exception as e:
            logger.error(f"GitHubModelsProvider.call error: {str(e)}")
            return {
                "content": "",
                "model_used": model_id,
                "provider": self.nombre,
                "success": False,
                "error": str(e)
            }
    
    def get_models(self) -> list[dict]:
        return self.GITHUB_MODELS.copy()


class ProviderManager:
    def __init__(self):
        self.providers = {
            "openrouter": OpenRouterProvider(),
            "anthropic": AnthropicProvider(),
            "openai": OpenAIProvider(),
            "ollama": OllamaProvider(),
            "groq": GroqProvider(),
            "github": GitHubModelsProvider()
        }
        self.priority_order = [
            p.strip() for p in
            settings.provider_priority.split(",")
        ]
        self._health_cache = {}
        self._health_timestamp = None
        self._health_ttl = 300
    
    def get_available_providers(self) -> list[str]:
        if not self._health_cache or (time.time() - (self._health_timestamp or 0) > self._health_ttl):
            self.health_check()
        
        available = []
        for provider_name in self.priority_order:
            if provider_name in self._health_cache.get("providers", {}):
                if self._health_cache["providers"][provider_name]["available"]:
                    available.append(provider_name)
        return available
    
    def get_all_models(self) -> list[dict]:
        all_models = []
        seen_ids = set()
        
        for provider_name in self.priority_order:
            if provider_name in self.providers:
                if self.providers[provider_name].is_available():
                    for model in self.providers[provider_name].get_models():
                        if model["id"] not in seen_ids:
                            seen_ids.add(model["id"])
                            all_models.append(model)
        
        all_models.sort(key=lambda x: x.get("quality_score", 50), reverse=True)
        return all_models
    
    def health_check(self) -> dict:
        try:
            providers_info = {}
            total_models = 0
            
            for name, provider in self.providers.items():
                available = provider.is_available()
                models = provider.get_models() if available else []
                models_count = len(models)
                total_models += models_count
                top_model = models[0]["id"] if models else None
                
                providers_info[name] = {
                    "available": available,
                    "models_count": models_count,
                    "top_model": top_model
                }
            
            best_planning = None
            best_generation = None
            best_correction = None
            
            try:
                from core.router import select_model
                best_planning = select_model("planning")
                best_generation = select_model("generation")
                best_correction = select_model("correction")
            except:
                pass
            
            result = {
                "timestamp": datetime.utcnow().isoformat(),
                "providers": providers_info,
                "total_models": total_models,
                "best_model_planning": best_planning,
                "best_model_generation": best_generation,
                "best_model_correction": best_correction
            }
            
            self._health_cache = result
            self._health_timestamp = time.time()
            
            logger.info(f"Health check complete: {total_models} models across {len([p for p in providers_info.values() if p['available']])} providers")
            return result
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "providers": {},
                "total_models": 0,
                "best_model_planning": None,
                "best_model_generation": None,
                "best_model_correction": None,
                "error": str(e)
            }
    
    def get_health_report(self) -> dict:
        if not self._health_cache or (time.time() - (self._health_timestamp or 0) > self._health_ttl):
            return self.health_check()
        return self._health_cache
    
    def call_with_fallback(
        self,
        model_id: str,
        messages: list[dict],
        max_tokens: int = 2000,
        temperature: float = 0.1
    ) -> dict:
        logger.info(f"call_with_fallback: model={model_id}")
        for name, provider in self.providers.items():
            logger.info(f"  Provider {name}: available={provider.is_available()}")
        
        target_provider = None
        target_score = None
        
        for provider_name in self.priority_order:
            if provider_name in self.providers:
                for model in self.providers[provider_name].get_models():
                    if model["id"] == model_id:
                        target_provider = provider_name
                        target_score = model.get("quality_score", 50)
                        break
            if target_provider:
                break
        
        if target_provider and target_provider in self.providers:
            result = self.providers[target_provider].call(
                model_id, messages, max_tokens, temperature
            )
            if result["success"]:
                return result
            if result.get("error") == "provider_unavailable":
                logger.warning(f"Provider '{target_provider}' unavailable, trying fallback providers")
        
        for provider_name in self.priority_order:
            if provider_name == target_provider:
                continue
            if provider_name not in self.providers:
                continue
            if not self.providers[provider_name].is_available():
                continue
            
            for model in self.providers[provider_name].get_models():
                model_score = model.get("quality_score", 50)
                if target_score and abs(model_score - target_score) <= 10:
                    result = self.providers[provider_name].call(
                        model["id"], messages, max_tokens, temperature
                    )
                    if result["success"]:
                        return result
                    if result.get("error") == "provider_unavailable":
                        continue
        
        for provider_name in self.priority_order:
            if provider_name in self.providers and self.providers[provider_name].is_available():
                models = self.providers[provider_name].get_models()
                if models:
                    best_model = max(models, key=lambda x: x.get("quality_score", 50))
                    result = self.providers[provider_name].call(
                        best_model["id"], messages, max_tokens, temperature
                    )
                    if result["success"]:
                        return result
        
        return {
            "content": "",
            "model_used": model_id,
            "provider": None,
            "success": False,
            "error": "No provider succeeded"
        }


provider_manager = ProviderManager()